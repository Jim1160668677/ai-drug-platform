"""双上下文筛选与新抗原疫苗端点

2 个端点：
- POST /screening/dual-context  — DualContextScreener 双上下文筛选
- POST /screening/vaccine        — HybridOrchestrator 新抗原到 mRNA 疫苗流水线
"""
import logging
from typing import Any, Dict, Optional

from fastapi import APIRouter, Depends

from app.core.deps import get_active_llm_config, get_current_user, get_llm_client_with_config, require_role_or_function
from app.core.exceptions import NotFoundError, ValidationError
from app.core.security import UserRole
from app.db.session import get_db
from app.models.user import User
from app.schemas.common import ApiResponse, success_response
from app.services.orchestrator.dual_context_screener import DualContextScreener
from app.services.orchestrator.hybrid_orchestrator import HybridOrchestrator
from app.services.coscientist.hooks import on_screening_completed, on_vaccine_designed
from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)
router = APIRouter()

_WRITE_ROLES = [UserRole.FOUNDER, UserRole.CHIEF_RESEARCHER, UserRole.RESEARCHER, UserRole.DOCTOR]
_WRITE_FUNCS = ["target_discovery", "molecule_design", "project_pi", "immunology"]


async def _get_llm(db: AsyncSession):
    try:
        llm_client = await get_llm_client_with_config(db)
        llm_config = await get_active_llm_config(db)
        return llm_client, llm_config
    except Exception as e:
        logger.warning(f"获取 LLM 客户端失败，降级纯计算: {e}")
        return None, None


@router.post("/dual-context", response_model=ApiResponse[Dict[str, Any]], summary="双上下文筛选")
async def dual_context_screen(
    payload: Dict[str, Any],
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role_or_function(_WRITE_ROLES, _WRITE_FUNCS)),
):
    """DualContextScreener（body: {smiles_list, target_pdb?, target_id?, contexts?}）

    启发自 Google C2S-Scale — 在免疫活跃 vs 中性两种上下文下筛选分子，
    发现 conditional_amplifier（条件放大器）。
    返回 {contexts, results, amplifiers, summary, n_amplifiers, threshold}
    """
    smiles_list = (payload or {}).get("smiles_list", [])
    if not smiles_list or not isinstance(smiles_list, list):
        raise ValidationError("smiles_list（数组）不能为空")

    target_pdb = payload.get("target_pdb", "")
    target_id = payload.get("target_id")
    contexts = payload.get("contexts")

    llm_client, llm_config = await _get_llm(db)
    screener = DualContextScreener(db, llm_client=llm_client, llm_config=llm_config)

    if target_id:
        result = await screener.screen_with_target(
            target_id=target_id, smiles_list=smiles_list,
            contexts=contexts, user_id=str(current_user.id),
        )
    else:
        result = await screener.screen(
            smiles_list=smiles_list, target_pdb=target_pdb,
            contexts=contexts, user_id=str(current_user.id),
        )
    await db.commit()
    # Co-Scientist auto-trigger: screening completed
    await on_screening_completed(
        db=db, user=current_user, project_id=None,
        job_id=str(result.get("job_id", "")) if isinstance(result, dict) and result.get("job_id") else None,
        job_name=f"dual-context-{target_id or 'no-target'}",
    )
    return success_response(result)


@router.post("/vaccine", response_model=ApiResponse[Dict[str, Any]], summary="新抗原到 mRNA 疫苗流水线")
async def vaccine_pipeline(
    payload: Dict[str, Any],
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role_or_function(_WRITE_ROLES, _WRITE_FUNCS)),
):
    """HybridOrchestrator.llm_to_vaccine_pipeline（body: {project_id, target_id, mutation_sequence, mhc_alleles?}）

    复现程序员救狗案例：ESMFold 预测结构 → MHCflurry 识别新抗原 → LLM 设计 mRNA 疫苗。
    返回 {structure, neoantigens, vaccine, cost_usd, duration_sec, steps_completed}
    """
    project_id = (payload or {}).get("project_id")
    target_id = (payload or {}).get("target_id")
    mutation_sequence = (payload or {}).get("mutation_sequence", "").strip()
    if not target_id or not mutation_sequence:
        raise ValidationError("target_id 和 mutation_sequence 不能为空")
    mhc_alleles = payload.get("mhc_alleles")

    llm_client, llm_config = await _get_llm(db)
    orchestrator = HybridOrchestrator(db, llm_client=llm_client, llm_config=llm_config)
    result = await orchestrator.llm_to_vaccine_pipeline(
        project_id=project_id, target_id=target_id,
        mutation_sequence=mutation_sequence, user=current_user,
        mhc_alleles=mhc_alleles,
    )
    await db.commit()
    # Co-Scientist auto-trigger: vaccine designed
    await on_vaccine_designed(
        db=db, user=current_user,
        project_id=str(project_id) if project_id else None,
        job_id=str(result.get("job_id", "")) if isinstance(result, dict) and result.get("job_id") else None,
        job_name=f"vaccine-{target_id}",
    )
    return success_response(result)
