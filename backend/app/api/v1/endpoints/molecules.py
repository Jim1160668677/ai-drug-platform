"""分子端点 — 分子设计与对接"""
import asyncio
import logging
from typing import Any, Dict, List, Optional
from uuid import UUID

from fastapi import APIRouter, Body, Depends, Query
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.authz import apply_molecule_visibility, apply_project_visibility
from app.core.deps import get_current_user
from app.core.exceptions import ForbiddenError, NotFoundError
from app.core.security import UserRole
from app.db.session import get_db
from app.models.molecule import Molecule
from app.models.project import Project
from app.models.target import Target
from app.models.user import User
from app.api.v1.schemas import MoleculeResponse, StandardResponse
from app.schemas.common import ApiResponse, PagedResponse, paged_response, success_response
from app.services.coscientist.hooks import on_molecule_generated

logger = logging.getLogger(__name__)
router = APIRouter()


class DesignRequest(BaseModel):
    target_id: Optional[str] = None
    smiles: Optional[str] = None
    constraints: Optional[dict] = None


class DockingRequest(BaseModel):
    """分子对接请求体

    protein_pdb 可能是 PDB ID（如 1A2C）或完整 PDB 文件内容（10KB-1MB）。
    使用 Body 而非 Query 避免超 URL 长度限制。
    """
    protein_pdb: str = Field(..., description="蛋白质 PDB 内容或 PDB ID")
    params: Optional[dict] = Field(None, description="对接参数（num_poses、seed 等）")


@router.get("", response_model=PagedResponse[MoleculeResponse], summary="分子列表")
async def list_molecules(
    target_id: UUID = Query(None),
    page: int = Query(1, ge=1, description="页码，从 1 开始"),
    page_size: int = Query(50, ge=1, le=200, description="每页条数"),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """获取分子列表（分页，PagedResponse 信封）

    可见性：领导角色可见全部；其余角色仅可见自己拥有项目下的靶点所关联的分子。
    孤立分子（无 target_id）对非领导角色不可见。

    当列表为空且未按 target_id 过滤时，自动基于当前用户项目的首个靶点
    生成一批候选分子（RDKit 片段组合 + 类药性评估）并持久化，避免空列表。
    分子名称会基于 SMILES 自动生成（骨架+功能团+分子式+哈希）。
    """
    skip = (page - 1) * page_size
    stmt = select(Molecule).offset(skip).limit(page_size).order_by(Molecule.created_at.desc())
    if target_id:
        stmt = stmt.where(Molecule.target_id == target_id)
    stmt = apply_molecule_visibility(stmt, current_user, Molecule.target_id)
    result = await db.execute(stmt)
    molecule_rows = result.scalars().all()

    # Lazy-fill：对 name 为空的分子，调用 generate_molecule_name 自动生成并持久化
    # 一次请求中批量命名，避免 N 次 API 调用
    unnamed = [m for m in molecule_rows if not m.name]
    if unnamed:
        import asyncio as _asyncio
        from app.services.analyzer.molecule_designer import generate_molecule_name
        for m in unnamed:
            try:
                m.name = await _asyncio.to_thread(generate_molecule_name, m.smiles, "Cand")
            except Exception as e:
                logger.warning(f"分子自动命名失败 smiles={m.smiles[:30]}: {e}")
        try:
            await db.commit()
            for m in unnamed:
                await db.refresh(m)
        except Exception as e:
            logger.warning(f"分子自动命名持久化失败: {e}")
            await db.rollback()

    items = [MoleculeResponse.model_validate(m).model_dump() for m in molecule_rows]

    # 空列表自动生成 — 仅在第 1 页、无 target_id 过滤、且当前用户可见范围为空时触发
    if not items and not target_id and page == 1:
        items = await _auto_generate_molecules(db, current_user)

    count_stmt = select(func.count()).select_from(Molecule)
    if target_id:
        count_stmt = count_stmt.where(Molecule.target_id == target_id)
    count_stmt = apply_molecule_visibility(count_stmt, current_user, Molecule.target_id)
    total = (await db.execute(count_stmt)).scalar() or 0
    return paged_response(data=items, page=page, page_size=page_size, total=total)


async def _auto_generate_molecules(db: AsyncSession, current_user: User) -> list:
    """为当前用户的项目靶点自动生成候选分子并自动评估、筛选、持久化。

    策略：
    1. 取用户可见范围内置信度最高的靶点（最多 3 个）
    2. 对每个靶点调用 MoleculeDesigner.generate_molecules 生成候选分子
    3. 用 assess_druglikeness 评估每个分子的类药性
    4. 筛选：保留通过 Lipinski 五规则且类药性评分 >= 60 的候选
    5. 按类药性评分降序排序，取前 10 个存入数据库
    """
    from app.services.analyzer.molecule_designer import MoleculeDesigner, assess_druglikeness

    # 查找用户可见的靶点 — 按置信度降序取前 3 个
    target_stmt = (
        select(Target)
        .order_by(Target.confidence_score.desc().nullslast())
        .limit(3)
    )
    target_stmt = apply_project_visibility(target_stmt, current_user, Target.project_id)
    target_result = await db.execute(target_stmt)
    targets = target_result.scalars().all()

    if not targets:
        return []

    designer = MoleculeDesigner(db)
    scored_candidates: list[tuple[float, dict, "Target", dict]] = []

    for target in targets:
        gen_result = await designer.generate_molecules(
            target_id=str(target.id),
            strategy="fragment",
            n=15,
            seed_smiles=None,
            constraints={},
        )

        molecules_data = gen_result.get("molecules", [])
        for mol in molecules_data:
            smiles = mol.get("smiles", "")
            if not smiles:
                continue
            props = assess_druglikeness(smiles)
            # 跳过无效 SMILES 或评估失败
            if props.get("error"):
                continue
            score = props.get("druglikeness_score", 0)
            passes_ro5 = props.get("passes_rule_of_five", False)
            # 筛选：通过 Lipinski 且评分 >= 60
            if passes_ro5 and score >= 60:
                scored_candidates.append((score, mol, target, props))

    if not scored_candidates:
        # 降级：如果没有通过筛选的，取评分最高的前几个
        for target in targets:
            gen_result = await designer.generate_molecules(
                target_id=str(target.id),
                strategy="fragment",
                n=10,
                seed_smiles=None,
                constraints={},
            )
            for mol in gen_result.get("molecules", []):
                smiles = mol.get("smiles", "")
                if not smiles:
                    continue
                props = assess_druglikeness(smiles)
                if props.get("error"):
                    continue
                score = props.get("druglikeness_score", 0)
                scored_candidates.append((score, mol, target, props))

    # 按类药性评分降序排序，取前 10 个
    scored_candidates.sort(key=lambda x: x[0], reverse=True)
    top_candidates = scored_candidates[:10]

    saved = []
    for score, mol, target, props in top_candidates:
        smiles = mol.get("smiles", "")
        # 自动生成分子名称（基于 SMILES 骨架+功能团+分子式+哈希）
        from app.services.analyzer.molecule_designer import generate_molecule_name
        auto_name = mol.get("name") or generate_molecule_name(smiles, prefix="Cand")
        new_mol = Molecule(
            target_id=target.id,
            smiles=smiles,
            name=auto_name,
            molecular_weight=props.get("mw"),
            logp=props.get("logp"),
            properties={
                **props,
                "source": mol.get("source", "auto_fragment"),
                "strategy": "fragment",
                "druglikeness_score": score,
            },
            designed_by="auto_fragment",
            source=mol.get("source", "auto_fragment"),
        )
        db.add(new_mol)
        saved.append(new_mol)

    if saved:
        await db.commit()
        await db.refresh(saved[0])

    return [MoleculeResponse.model_validate(m).model_dump() for m in saved]


@router.post("/design", response_model=StandardResponse, summary="分子设计（P2）")
async def design_molecule(
    payload: DesignRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """分子设计 — DeepChem 性质预测（第二阶段）

    修复 BUG-002：增加 60s 超时保护，避免 mock 模式下阻塞。
    mock 模式由 MoleculeDesigner.design() 入口快速返回预置分子集。
    """
    from app.services.analyzer.molecule_designer import MoleculeDesigner
    designer = MoleculeDesigner(db)
    try:
        result = await asyncio.wait_for(
            designer.design(payload.model_dump()), timeout=60.0
        )
    except asyncio.TimeoutError:
        from app.core.exceptions import TaskTimeoutError
        raise TaskTimeoutError("分子设计超时（60s），请检查配置或减少分子数量", timeout_sec=60)
    return StandardResponse(message="分子设计完成", data=result)


@router.post("/design-multi-target", response_model=ApiResponse[Dict[str, Any]], summary="多靶点协同分子设计")
async def design_multi_target_molecules(
    targets: List[Dict[str, Any]] = Body(..., embed=True, description="靶点列表 [{target_id, name, binding_site, weight, gene_symbol, pdb_id}]"),
    seed_smiles: str = Body(None, embed=True),
    constraints: dict = Body(None, embed=True),
    n_molecules: int = Body(10, embed=True),
    use_llm: bool = Body(False, embed=True, description="是否启用 LLM 辅助设计"),
    use_docking: bool = Body(False, embed=True, description="是否启用 DiffDock 对接（Mock 模式）"),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """多靶点协同分子设计

    支持同时输入多个药物靶点信息，基于多靶点相互作用机制进行药物分子设计。
    每个分子结果单独成行，包含分子结构(SMILES + 结构图)、理化性质、各靶点结合亲和力（列表）、综合评分、设计理由。

    可选功能：
    - use_llm=True: 启用 LLM 辅助生成候选分子（需要 Agnes API 配置）
    - use_docking=True: 启用 DiffDock 对接计算真实亲和力（NVIDIA_NIM_API_KEY 配置时，否则 Mock）
    """
    if not targets or len(targets) < 1:
        from app.core.exceptions import ValidationError
        raise ValidationError("至少需要提供 1 个靶点")
    if len(targets) > 10:
        from app.core.exceptions import ValidationError
        raise ValidationError("靶点数量不能超过 10 个")

    from app.services.analyzer.molecule_designer import MoleculeDesigner
    designer = MoleculeDesigner(db)

    # 获取 LLM 客户端（如启用）
    llm_client = None
    if use_llm:
        try:
            from app.core.deps import get_llm_client_with_config
            llm_client = await get_llm_client_with_config(db)
        except Exception as e:
            logger.warning(f"LLM 客户端获取失败，降级规则生成: {e}")

    result = await asyncio.wait_for(
        designer.design_multi_target(
            targets, seed_smiles, constraints, n_molecules,
            use_llm=use_llm, use_docking=use_docking, llm_client=llm_client,
        ),
        timeout=120.0,
    )
    return success_response(result)


@router.post("/{molecule_id}/dock", response_model=StandardResponse, summary="分子对接（P2）")
async def dock_molecule(
    molecule_id: UUID,
    payload: DockingRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """分子对接 — DiffDock（第二阶段）

    使用 Body 接收 protein_pdb（PDB 文件内容可达 10KB-1MB，超 URL 长度限制）。
    """
    from app.core.deps import get_diffdock_client
    mol = await db.get(Molecule, molecule_id)
    if not mol:
        raise NotFoundError("分子不存在")
    # 权限校验：与 get_molecule 一致（molecule→target→project→owner）
    if not mol.target_id:
        if current_user.role != UserRole.FOUNDER:
            raise ForbiddenError("无权操作此资源")
    else:
        target = await db.get(Target, mol.target_id)
        if not target:
            if current_user.role != UserRole.FOUNDER:
                raise ForbiddenError("无权操作此资源")
        else:
            project = await db.get(Project, target.project_id)
            if current_user.role != UserRole.FOUNDER and (not project or project.owner_id != current_user.id):
                raise ForbiddenError("无权操作此资源")

    client = get_diffdock_client()
    result = await client.dock(protein_pdb=payload.protein_pdb, ligand_smiles=mol.smiles)
    mol.docking_result = result
    return StandardResponse(message="对接完成", data=result)


@router.post("/assess", response_model=StandardResponse, summary="类药性评估")
async def assess_druglikeness(
    smiles: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """类药性评估 — Lipinski 五规则（RDKit）

    将同步 CPU 密集的 RDKit 计算包装为 asyncio.to_thread，避免阻塞事件循环。
    """
    from app.services.analyzer.molecule_designer import assess_druglikeness as _assess
    result = await asyncio.to_thread(_assess, smiles)
    return success_response(result)


@router.post("/auto-name", response_model=ApiResponse[Dict[str, Any]], summary="分子自动命名")
async def auto_name_molecule(
    smiles: str = Body(..., embed=True, description="分子 SMILES"),
    prefix: str = Body("Mol", embed=True, description="名称前缀（如 Mol、Cand）"),
    current_user: User = Depends(get_current_user),
):
    """基于 SMILES 自动生成有意义的分子名称

    策略：RDKit Murcko 骨架 → 中文骨架名 + 主要功能团 + 分子式 + SMILES 哈希短码
    RDKit 不可用时降级为字符级特征命名（保证功能可用）。

    Returns:
        {name, smiles, prefix}
    """
    from app.services.analyzer.molecule_designer import generate_molecule_name
    name = await asyncio.to_thread(generate_molecule_name, smiles, prefix)
    return success_response({"name": name, "smiles": smiles, "prefix": prefix})


@router.post("/assess-druglikeness", response_model=ApiResponse[Dict[str, Any]], summary="类药性评估")
async def assess_druglikeness_v2(
    smiles: str = Body(..., embed=True),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """评估分子类药性（Lipinski/Veber/QED）

    将同步 CPU 密集的 RDKit 计算包装为 asyncio.to_thread，避免阻塞事件循环。
    """
    from app.services.analyzer.molecule_designer import assess_druglikeness as _assess
    result = await asyncio.to_thread(_assess, smiles)
    return success_response(result)


@router.post("/predict-properties", response_model=ApiResponse[Dict[str, Any]], summary="ADMET 性质预测")
async def predict_properties(
    smiles: str = Body(..., embed=True),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """预测 ADMET 性质 — RDKit 计算 8 项指标

    将同步 CPU 密集的 RDKit 计算包装为 asyncio.to_thread，避免阻塞事件循环。
    """
    from app.services.analyzer.molecule_designer import predict_admet
    result = await asyncio.to_thread(predict_admet, smiles)
    return success_response(result)


@router.post("/{molecule_id}/assess-developability", response_model=ApiResponse[Dict[str, Any]], summary="药物可开发性评估")
async def assess_developability(
    molecule_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """触发药物可开发性评估（5 维度：合成/毒理/制剂/成本/综合）

    在分子送入湿实验前先用算法做预筛选，把明显不可合成/高毒/高成本的分子挡在湿实验门外。
    返回 go/revise/no_go 决策建议。
    """
    import asyncio
    from app.services.molecule import DevelopabilityAssessor

    mol = await db.get(Molecule, molecule_id)
    if not mol:
        raise NotFoundError("分子不存在")
    # 权限校验：与 get_molecule 一致（molecule→target→project→owner）
    if not mol.target_id:
        if current_user.role != UserRole.FOUNDER:
            raise ForbiddenError("无权操作此资源")
    else:
        target = await db.get(Target, mol.target_id)
        if not target:
            if current_user.role != UserRole.FOUNDER:
                raise ForbiddenError("无权操作此资源")
        else:
            project = await db.get(Project, target.project_id)
            if current_user.role != UserRole.FOUNDER and (not project or project.owner_id != current_user.id):
                raise ForbiddenError("无权操作此资源")

    assessor = DevelopabilityAssessor(db)
    # CPU 密集计算（RDKit）用 to_thread 包装避免阻塞事件循环
    # 但 assess 内部含 DB 操作，整体保留 async；同步子计算由底层函数处理
    assessment = await assessor.assess(mol, created_by=current_user.id)
    return success_response(_serialize_assessment(assessment))


@router.get("/{molecule_id}/developability", response_model=ApiResponse[List[Dict[str, Any]]], summary="历史可开发性评估记录")
async def list_developability(
    molecule_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """查询分子的历史可开发性评估记录（按版本倒序）"""
    from app.models.developability import DevelopabilityAssessment

    mol = await db.get(Molecule, molecule_id)
    if not mol:
        raise NotFoundError("分子不存在")
    # 权限校验：与 get_molecule 一致
    if not mol.target_id:
        if current_user.role != UserRole.FOUNDER:
            raise ForbiddenError("无权访问此资源")
    else:
        target = await db.get(Target, mol.target_id)
        if not target:
            if current_user.role != UserRole.FOUNDER:
                raise ForbiddenError("无权访问此资源")
        else:
            project = await db.get(Project, target.project_id)
            if current_user.role != UserRole.FOUNDER and (not project or project.owner_id != current_user.id):
                raise ForbiddenError("无权访问此资源")

    stmt = (
        select(DevelopabilityAssessment)
        .where(DevelopabilityAssessment.molecule_id == molecule_id)
        .order_by(DevelopabilityAssessment.version.desc())
    )
    results = (await db.execute(stmt)).scalars().all()
    return success_response([_serialize_assessment(a) for a in results])


def _serialize_assessment(a: "DevelopabilityAssessment") -> Dict[str, Any]:
    """序列化 DevelopabilityAssessment ORM 对象为 dict"""
    return {
        "id": str(a.id),
        "molecule_id": str(a.molecule_id),
        "project_id": str(a.project_id) if a.project_id else None,
        "version": a.version,
        "sa_score": a.sa_score,
        "sa_ease_label": a.sa_ease_label,
        "toxicity_risk": a.toxicity_risk,
        "toxicity_alerts": a.toxicity_alerts or [],
        "formulation_score": a.formulation_score,
        "formulation_notes": a.formulation_notes,
        "cost_estimate_usd": a.cost_estimate_usd,
        "cost_breakdown": a.cost_breakdown or {},
        "overall_score": a.overall_score,
        "recommendation": a.recommendation,
        "rationale": a.rationale,
        "created_at": a.created_at.isoformat() if a.created_at else None,
    }


@router.post("/generate", response_model=ApiResponse[Dict[str, Any]], summary="分子生成")
async def generate_molecules(
    target_id: str = Body(..., embed=True),
    strategy: str = Body("fragment", embed=True),
    n: int = Body(10, embed=True),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """生成新分子"""
    from app.services.analyzer.molecule_designer import MoleculeDesigner
    designer = MoleculeDesigner(db)
    result = await designer.generate_molecules(target_id=target_id, strategy=strategy, n=n)

    # Co-Scientist auto-trigger hook
    _gen_mols = result.get("molecules", []) if isinstance(result, dict) else []
    if _gen_mols:
        _gm0 = _gen_mols[0]
        await on_molecule_generated(
            db=db, user=current_user, project_id=None,
            molecule_id=str(_gm0.get("id")) if _gm0.get("id") else None,
            molecule_name=_gm0.get("name"),
        )
    return success_response(result)


@router.post("/explain", response_model=ApiResponse[Dict[str, Any]], summary="分子可解释性")
async def explain_molecule(
    smiles: str = Body(..., embed=True),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """分子结构可解释性分析 — RDKit SMARTS 功能团识别

    将同步 CPU 密集的 RDKit 计算包装为 asyncio.to_thread，避免阻塞事件循环。
    """
    from app.services.analyzer.molecule_designer import explain_molecule as _explain
    result = await asyncio.to_thread(_explain, smiles)
    return success_response(result)


@router.get("/models", response_model=ApiResponse[Dict[str, Any]], summary="可用模型列表")
async def list_models(
    current_user: User = Depends(get_current_user),
):
    """列出可用的分子设计模型"""
    return success_response({
        "models": [
            {"name": "fragment_based", "description": "片段组合策略"},
            {"name": "optimization", "description": "取代基优化策略"},
            {"name": "random", "description": "骨架随机策略"},
        ]
    })


@router.get("/{molecule_id}", response_model=MoleculeResponse, summary="分子详情")
async def get_molecule(
    molecule_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """获取分子详情"""
    mol = await db.get(Molecule, molecule_id)
    if not mol:
        raise NotFoundError("分子不存在")
    # 多级关联：molecule.target_id → target.project_id → project.owner_id
    if not mol.target_id:
        # 无 target_id 的孤立分子无法确定归属，仅 FOUNDER 可访问
        if current_user.role != UserRole.FOUNDER:
            raise ForbiddenError("无权访问此资源")
    else:
        target = await db.get(Target, mol.target_id)
        if not target:
            if current_user.role != UserRole.FOUNDER:
                raise ForbiddenError("无权访问此资源")
        else:
            project = await db.get(Project, target.project_id)
            if current_user.role != UserRole.FOUNDER and (not project or project.owner_id != current_user.id):
                raise ForbiddenError("无权访问此资源")
    return MoleculeResponse.model_validate(mol)


@router.delete("/{molecule_id}", response_model=ApiResponse[Dict[str, Any]], summary="删除分子")
async def delete_molecule(
    molecule_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """删除分子（仅 FOUNDER 或分子所属项目拥有者可删除）"""
    mol = await db.get(Molecule, molecule_id)
    if not mol:
        raise NotFoundError("分子不存在")
    # 权限校验：与 get_molecule 一致
    if not mol.target_id:
        if current_user.role != UserRole.FOUNDER:
            raise ForbiddenError("无权删除此资源")
    else:
        target = await db.get(Target, mol.target_id)
        if not target:
            if current_user.role != UserRole.FOUNDER:
                raise ForbiddenError("无权删除此资源")
        else:
            project = await db.get(Project, target.project_id)
            if current_user.role != UserRole.FOUNDER and (not project or project.owner_id != current_user.id):
                raise ForbiddenError("无权删除此资源")
    await db.delete(mol)
    await db.commit()
    return success_response({"id": str(molecule_id), "deleted": True})


@router.get("/{molecule_id}/docking-results", response_model=ApiResponse[Dict[str, Any]], summary="对接结果")
async def get_docking_results(
    molecule_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """获取分子对接结果"""
    # 权限校验：与 get_molecule 一致（molecule→target→project→owner）
    mol = await db.get(Molecule, molecule_id)
    if not mol:
        raise NotFoundError("分子不存在")
    if not mol.target_id:
        if current_user.role != UserRole.FOUNDER:
            raise ForbiddenError("无权访问此资源")
    else:
        target = await db.get(Target, mol.target_id)
        if not target:
            if current_user.role != UserRole.FOUNDER:
                raise ForbiddenError("无权访问此资源")
        else:
            project = await db.get(Project, target.project_id)
            if current_user.role != UserRole.FOUNDER and (not project or project.owner_id != current_user.id):
                raise ForbiddenError("无权操作此资源")
    from app.models.molecule import DockingResult
    results = (await db.execute(
        select(DockingResult).where(DockingResult.molecule_id == molecule_id)
    )).scalars().all()
    return success_response({
        "molecule_id": str(molecule_id),
        "docking_results": [
            {
                "id": str(r.id),
                "protein_pdb_id": r.protein_pdb_id,
                "top_confidence": r.top_confidence,
                "poses": r.poses,
                "docked_by": r.docked_by,
            }
            for r in results
        ],
    })
