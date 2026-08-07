"""分子工具组 — 4 个工具

工具列表：
- design_molecules       单靶点分子设计（委托 MoleculeDesigner.generate_molecules）
- design_multi_target    多靶点协同分子设计（委托 MoleculeDesigner.design_multi_target）
- assess_druglikeness    类药性评估（委托 assess_druglikeness，已 to_thread）
- dock_molecule          分子对接（委托 DiffDockClient）— 副作用，需确认
"""
import asyncio
import logging
from typing import Any, Dict
from uuid import UUID

from app.core.security import UserRole
from app.models.molecule import Molecule
from app.models.project import Project
from app.models.target import Target
from app.services.agent.tools.base import (
    AgentTool,
    ToolContext,
    ToolParameter,
    ToolResult,
)

logger = logging.getLogger(__name__)


async def _check_molecule_access(ctx: ToolContext, molecule_id: str) -> bool:
    """校验分子访问权：FOUNDER 全权，其余通过 molecule→target→project→owner 链"""
    if ctx.user.role == UserRole.FOUNDER:
        return True
    mol = await ctx.db.get(Molecule, UUID(molecule_id))
    if mol is None or not mol.target_id:
        return False
    target = await ctx.db.get(Target, mol.target_id)
    if target is None:
        return False
    project = await ctx.db.get(Project, target.project_id)
    return project is not None and project.owner_id == ctx.user.id


class DesignMoleculesTool(AgentTool):
    """单靶点分子设计 — 委托 MoleculeDesigner.generate_molecules"""

    name = "design_molecules"
    description = (
        "为指定靶点设计候选分子。"
        "支持片段组合 / 取代基优化 / 骨架随机三种策略。"
        "返回候选分子列表（含 SMILES、类药性、预测活性）。"
    )
    parameters = [
        ToolParameter("target_id", "string", "靶点 ID", required=True),
        ToolParameter(
            "strategy",
            "string",
            "生成策略",
            required=False,
            default="fragment",
            enum=["fragment", "optimization", "random"],
        ),
        ToolParameter("n", "integer", "生成数量（1-50）", required=False, default=10),
        ToolParameter("seed_smiles", "string", "种子分子 SMILES（optimization 策略）", required=False),
        ToolParameter("constraints", "object", "约束条件（如 mw_max, logp_max）", required=False),
    ]
    side_effects = False
    required_role = UserRole.RESEARCHER

    async def execute(self, params: Dict[str, Any], ctx: ToolContext) -> ToolResult:
        from app.services.analyzer.molecule_designer import MoleculeDesigner

        target_id = params["target_id"]
        strategy = params.get("strategy", "fragment")
        n = min(max(params.get("n", 10), 1), 50)
        seed_smiles = params.get("seed_smiles")
        constraints = params.get("constraints", {}) or {}

        # 权限校验（通过 target）
        if ctx.user.role != UserRole.FOUNDER:
            target = await ctx.db.get(Target, UUID(target_id))
            if target is None:
                return ToolResult.fail(error="靶点不存在")
            project = await ctx.db.get(Project, target.project_id)
            if project is None or project.owner_id != ctx.user.id:
                return ToolResult.fail(error="无权操作此靶点")

        try:
            designer = MoleculeDesigner(ctx.db)
            result = await designer.generate_molecules(
                target_id=target_id,
                strategy=strategy,
                n=n,
                seed_smiles=seed_smiles,
                constraints=constraints,
            )
            return ToolResult.ok(
                data=result,
                display={"type": "molecule_list", "payload": result},
            )
        except Exception as e:
            logger.error(f"design_molecules 失败: {e}", exc_info=True)
            return ToolResult.fail(error=str(e))


class DesignMultiTargetTool(AgentTool):
    """多靶点协同分子设计 — 委托 MoleculeDesigner.design_multi_target"""

    name = "design_multi_target"
    description = (
        "为多个靶点协同设计分子。"
        "支持 LLM 辅助设计与 DiffDock 对接验证（可选）。"
        "返回候选分子及其对每个靶点的结合亲和力。"
    )
    parameters = [
        ToolParameter(
            "targets",
            "array",
            "靶点列表 [{target_id, name, binding_site, weight, gene_symbol, pdb_id}]",
            required=True,
        ),
        ToolParameter("seed_smiles", "string", "种子分子 SMILES", required=False),
        ToolParameter("constraints", "object", "约束条件", required=False),
        ToolParameter("n_molecules", "integer", "生成分子数", required=False, default=10),
        ToolParameter("use_llm", "boolean", "是否启用 LLM 辅助", required=False, default=False),
        ToolParameter("use_docking", "boolean", "是否启用 DiffDock 对接", required=False, default=False),
    ]
    side_effects = False
    required_role = UserRole.RESEARCHER

    async def execute(self, params: Dict[str, Any], ctx: ToolContext) -> ToolResult:
        from app.services.analyzer.molecule_designer import MoleculeDesigner

        targets = params["targets"]
        if not targets or not isinstance(targets, list):
            return ToolResult.fail(error="targets 必须是非空数组")
        if len(targets) > 10:
            return ToolResult.fail(error="靶点数量不能超过 10 个")

        # 权限校验：所有 target 必须可访问
        if ctx.user.role != UserRole.FOUNDER:
            for t in targets:
                tid = t.get("target_id")
                if tid:
                    target = await ctx.db.get(Target, UUID(tid))
                    if target is None:
                        return ToolResult.fail(error=f"靶点不存在: {tid}")
                    project = await ctx.db.get(Project, target.project_id)
                    if project is None or project.owner_id != ctx.user.id:
                        return ToolResult.fail(error=f"无权操作靶点: {tid}")

        try:
            designer = MoleculeDesigner(ctx.db)
            # 获取 LLM 客户端（如启用）
            llm_client = None
            if params.get("use_llm"):
                try:
                    from app.services.llm.router import LLMRouter
                    # 简化：使用 None llm_config，让 router 用 settings 默认
                    # 实际生产应通过依赖注入获取
                    llm_client = None  # 由 designer 内部降级处理
                except Exception as e:
                    logger.warning(f"LLM 客户端获取失败: {e}")

            result = await designer.design_multi_target(
                targets,
                params.get("seed_smiles"),
                params.get("constraints", {}) or {},
                params.get("n_molecules", 10),
                use_llm=params.get("use_llm", False),
                use_docking=params.get("use_docking", False),
                llm_client=llm_client,
            )
            return ToolResult.ok(
                data=result,
                display={"type": "molecule_list", "payload": result},
            )
        except Exception as e:
            logger.error(f"design_multi_target 失败: {e}", exc_info=True)
            return ToolResult.fail(error=str(e))


class AssessDruglikenessTool(AgentTool):
    """类药性评估 — 委托 assess_druglikeness（同步，已 to_thread 包装）"""

    name = "assess_druglikeness"
    description = (
        "评估分子的类药性：Lipinski 五规则、Veber 规则、QED 评分。"
        "返回分子量、LogP、氢键供体/受体数、旋转键数等指标。"
    )
    parameters = [
        ToolParameter("smiles", "string", "分子 SMILES 字符串", required=True),
    ]
    side_effects = False
    required_role = UserRole.RESEARCHER

    async def execute(self, params: Dict[str, Any], ctx: ToolContext) -> ToolResult:
        from app.services.analyzer.molecule_designer import assess_druglikeness

        smiles = params["smiles"]
        try:
            # 同步函数用 asyncio.to_thread 包装，避免阻塞事件循环
            result = await asyncio.to_thread(assess_druglikeness, smiles)
            if result.get("error"):
                return ToolResult.fail(
                    error=result["error"],
                    data=result,
                )
            return ToolResult.ok(
                data=result,
                display={"type": "stats", "payload": result},
            )
        except Exception as e:
            logger.error(f"assess_druglikeness 失败: {e}", exc_info=True)
            return ToolResult.fail(error=str(e))


class DockMoleculeTool(AgentTool):
    """分子对接 — 委托 DiffDockClient.dock（副作用，需确认）"""

    name = "dock_molecule"
    description = (
        "执行分子-蛋白对接计算（DiffDock）。"
        "输入分子 ID 和蛋白质 PDB 内容/PDB ID，返回对接姿态与亲和力。"
    )
    parameters = [
        ToolParameter("molecule_id", "string", "分子 ID", required=True),
        ToolParameter(
            "protein_pdb",
            "string",
            "蛋白质 PDB 内容或 PDB ID（如 1A2C）",
            required=True,
        ),
        ToolParameter("params", "object", "对接参数（num_poses、seed 等）", required=False),
    ]
    side_effects = True  # 调用外部 DiffDock 服务，标记为副作用
    required_role = UserRole.RESEARCHER

    async def execute(self, params: Dict[str, Any], ctx: ToolContext) -> ToolResult:
        from app.core.deps import get_diffdock_client

        molecule_id = params["molecule_id"]
        protein_pdb = params["protein_pdb"]
        dock_params = params.get("params", {}) or {}

        # 权限校验
        if not await _check_molecule_access(ctx, molecule_id):
            return ToolResult.fail(error="无权操作此分子")

        try:
            mol = await ctx.db.get(Molecule, UUID(molecule_id))
            if mol is None:
                return ToolResult.fail(error=f"分子不存在: {molecule_id}")

            client = get_diffdock_client()
            result = await client.dock(
                protein_pdb=protein_pdb,
                ligand_smiles=mol.smiles,
                **dock_params,
            )
            # 持久化对接结果
            mol.docking_result = result
            await ctx.db.flush()

            return ToolResult.ok(
                data=result,
                display={"type": "docking", "payload": result},
            )
        except Exception as e:
            logger.error(f"dock_molecule 失败: {e}", exc_info=True)
            return ToolResult.fail(error=str(e))
