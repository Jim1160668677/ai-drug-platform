"""双上下文筛选器 — 启发自 Google C2S-Scale 论文「双上下文虚拟筛选」

在「免疫活跃」vs「中性」两种生物学上下文下分别筛选分子，
发现"条件放大器"（conditional amplifier）— 仅在特定上下文下显效的分子。

核心创新点（论文）：
- 同一分子在不同生物学上下文下的 efficacy 差异 = conditional amplification
- conditional_amplification_score = efficacy(immune_active) - efficacy(neutral)，范围 [-1, 1]
- score > DUAL_CONTEXT_AMPLIFIER_THRESHOLD (0.2) 即条件放大器

设计原则：
- 复用 Uni-Mol 对接引擎（get_unimol，Mock/Real 双模式）
- 复用 LLMOrchestrator.select_model 进行模型选择
- 容错：单分子对接失败不影响其他分子，记录 warning 后继续
- 成本控制：LLM 调用累计 cost_usd 超过 HYBRID_MAX_COST_USD 时终止
- 降级：LLM 返回 JSON 解析失败时降级为空列表
"""
import json
import logging
import uuid
from typing import Any, Dict, List, Optional, Tuple

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.exceptions import NotFoundError
from app.services.compute import get_unimol
from app.services.llm.prompts import SYSTEM_PROMPTS

logger = logging.getLogger(__name__)


def _to_uuid(value: Any) -> Optional[uuid.UUID]:
    """把 str/UUID 统一转为 UUID（SQLAlchemy Uuid 列要求 UUID 对象）

    None 透传；非法格式抛 ValueError（调用方应确保合法）。
    """
    if value is None:
        return None
    if isinstance(value, uuid.UUID):
        return value
    return uuid.UUID(value)


# 默认双上下文 — 免疫活跃 vs 中性
_DEFAULT_CONTEXTS: List[str] = ["immune_active", "neutral"]

# 免疫激活偏移（Mock 模式下的确定性偏移）
_IMMUNE_ACTIVE_OFFSET: float = 0.1


def _is_active_context(context: str) -> bool:
    """判断是否为免疫活跃上下文（应用激活偏移）

    匹配含 "immune" 或 "active" 的上下文名。
    """
    ctx_lower = (context or "").lower()
    return "immune" in ctx_lower or "active" in ctx_lower


def _compute_efficacy(docking: Dict[str, Any], context: str) -> float:
    """计算分子在指定上下文下的 efficacy 分数

    efficacy = (1.0 / (1.0 + abs(affinity))) * confidence  # 0-1，越大越好
    immune_active 上下文额外加确定性偏移 0.1（Mock 模式）。

    Args:
        docking: unimol.dock() 返回的 {rmsd, affinity, confidence, ...}
        context: 上下文名称
    Returns:
        efficacy 分数 [0, ~1.1]
    """
    affinity = float(docking.get("affinity", 0.0) or 0.0)
    confidence = float(docking.get("confidence", 0.0) or 0.0)
    base = (1.0 / (1.0 + abs(affinity))) * confidence
    if _is_active_context(context):
        base += _IMMUNE_ACTIVE_OFFSET
    return round(base, 4)


class DualContextScreener:
    """双上下文筛选器 — 启发自 Google C2S-Scale 论文

    在免疫活跃 vs 中性两种生物学上下文下分别筛选分子，
    通过 efficacy 差异识别"条件放大器"。
    """

    def __init__(self, db: AsyncSession, llm_client=None, llm_config=None):
        """初始化

        Args:
            db: 异步数据库会话
            llm_client: LLM 客户端实例（Mock 或 Real），None 时跳过 LLM 解读
            llm_config: 数据库激活的 LLMConfig（可选，用于动态选择模型）
        """
        self.db = db
        self.llm_client = llm_client
        # 复用 LLMOrchestrator 的 select_model
        if llm_client is not None:
            from app.services.llm.orchestrator import LLMOrchestrator

            self.llm_orchestrator = LLMOrchestrator(db, llm_client, llm_config)
        else:
            self.llm_orchestrator = None

    async def screen(
        self,
        smiles_list: List[str],
        target_pdb: str = "",
        contexts: Optional[List[str]] = None,
        user_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        """双上下文筛选 — 核心方法

        对每个上下文下的每个分子调用 unimol.dock()，计算 efficacy 差异，
        筛选条件放大器（score > DUAL_CONTEXT_AMPLIFIER_THRESHOLD）。

        Args:
            smiles_list: 候选分子 SMILES 列表
            target_pdb: 受体 PDB 文本或 ID（Mock 模式下不影响结果）
            contexts: 上下文列表，默认 ["immune_active", "neutral"]
            user_id: 用户 ID（用于成本追踪，可选）
        Returns:
            {contexts, results, amplifiers, summary, n_amplifiers,
             n_total, threshold, source}
        """
        ctx_list = list(contexts) if contexts else list(_DEFAULT_CONTEXTS)
        # 至少需要两个上下文才能计算差异
        if len(ctx_list) < 2:
            ctx_list = list(_DEFAULT_CONTEXTS)

        unimol = get_unimol(self.db)
        threshold = float(getattr(settings, "DUAL_CONTEXT_AMPLIFIER_THRESHOLD", 0.2))
        max_cost = float(getattr(settings, "HYBRID_MAX_COST_USD", 50.0))

        # 识别 active / neutral 上下文
        active_ctx = next((c for c in ctx_list if _is_active_context(c)), ctx_list[0])
        neutral_ctx = next(
            (c for c in ctx_list if not _is_active_context(c)), ctx_list[-1]
        )

        results: List[Dict[str, Any]] = []
        for smiles in smiles_list:
            if not smiles:
                continue
            try:
                docking_active = await unimol.dock(
                    smiles=smiles, target_pdb=target_pdb, target_name=active_ctx
                )
                docking_neutral = await unimol.dock(
                    smiles=smiles, target_pdb=target_pdb, target_name=neutral_ctx
                )
            except Exception as e:
                # 单分子对接失败不影响其他分子
                logger.warning(f"分子 {smiles[:30]}... 对接失败，跳过: {e}")
                continue

            efficacy_active = _compute_efficacy(docking_active, active_ctx)
            efficacy_neutral = _compute_efficacy(docking_neutral, neutral_ctx)
            score = round(efficacy_active - efficacy_neutral, 4)

            results.append(
                {
                    "smiles": smiles,
                    "efficacy_active": efficacy_active,
                    "efficacy_neutral": efficacy_neutral,
                    "conditional_amplification_score": score,
                    "is_amplifier": score > threshold,
                    "docking_active": docking_active,
                    "docking_neutral": docking_neutral,
                }
            )

        # 筛选条件放大器
        amplifier_entries: List[Dict[str, Any]] = [
            r for r in results if r["is_amplifier"]
        ]

        summary = ""
        amplifiers: List[Dict[str, Any]] = []
        source = "mock"
        total_cost = 0.0

        # LLM 解读（如可用且有结果）
        if (
            self.llm_client is not None
            and self.llm_orchestrator is not None
            and results
        ):
            # 成本控制：累计 cost_usd 超过预算时终止 LLM 调用
            if total_cost >= max_cost:
                logger.warning(
                    f"累计 LLM 成本 ${total_cost:.4f} 已达预算 ${max_cost:.4f}，跳过解读"
                )
            else:
                try:
                    amplifiers, summary, llm_cost = await self._interpret_with_llm(
                        amplifier_entries,
                        active_ctx,
                        neutral_ctx,
                        threshold,
                        user_id,
                    )
                    total_cost += llm_cost
                    if llm_cost > 0:
                        source = "llm+mock"
                except Exception as e:
                    logger.warning(f"LLM 解读失败，降级纯计算结果: {e}")
                    amplifiers = [
                        {
                            "smiles": a["smiles"],
                            "score": a["conditional_amplification_score"],
                            "mechanism": "",
                        }
                        for a in amplifier_entries
                    ]
        else:
            # 纯计算结果（无 LLM 或无结果）
            amplifiers = [
                {
                    "smiles": a["smiles"],
                    "score": a["conditional_amplification_score"],
                    "mechanism": "",
                }
                for a in amplifier_entries
            ]

        return {
            "contexts": ctx_list,
            "results": results,
            "amplifiers": amplifiers,
            "summary": summary,
            "n_amplifiers": len(amplifier_entries),
            "n_total": len(results),
            "threshold": threshold,
            "source": source,
        }

    async def screen_with_target(
        self,
        target_id: str,
        smiles_list: List[str],
        contexts: Optional[List[str]] = None,
        user_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        """便捷方法 — 通过 target_id 加载靶点信息后调用 screen()

        从 DB 加载 Target（gene_symbol + 已知结合位点），target_pdb 在 Mock
        模式下不影响结果，可传空。

        Args:
            target_id: 靶点 ID
            smiles_list: 候选分子 SMILES 列表
            contexts: 上下文列表（可选）
            user_id: 用户 ID（可选）
        Returns:
            同 screen()，附加 target_id / target_gene
        Raises:
            NotFoundError: 靶点不存在
        """
        from app.models.target import Target

        target = await self.db.get(Target, _to_uuid(target_id))
        if not target:
            raise NotFoundError("靶点不存在")

        # target_pdb 可为空（Mock 模式下不影响结果）
        target_pdb = ""
        gene_symbol = target.gene_symbol or ""

        logger.info(
            f"双上下文筛选启动: target={gene_symbol} ({target_id}), "
            f"分子数={len(smiles_list)}"
        )

        result = await self.screen(
            smiles_list=smiles_list,
            target_pdb=target_pdb,
            contexts=contexts,
            user_id=user_id,
        )
        result["target_id"] = str(target.id)
        result["target_gene"] = gene_symbol
        return result

    async def _interpret_with_llm(
        self,
        amplifier_entries: List[Dict[str, Any]],
        active_ctx: str,
        neutral_ctx: str,
        threshold: float,
        user_id: Optional[str],
    ) -> Tuple[List[Dict[str, Any]], str, float]:
        """调用 LLM 解读条件放大器结果

        使用 SYSTEM_PROMPTS["dual_context_interpretation"] 解读，
        返回 amplifiers（含 mechanism）+ summary。

        Args:
            amplifier_entries: 条件放大器结果列表
            active_ctx: 免疫活跃上下文名
            neutral_ctx: 中性上下文名
            threshold: 放大器阈值
            user_id: 用户 ID（预留）
        Returns:
            (amplifiers, summary, cost_usd)
        """
        from app.models.analysis_job import AnalysisTier
        from app.services.llm.orchestrator import _estimate_cost

        # 构造上下文 prompt
        amp_data = [
            {
                "smiles": a["smiles"],
                "efficacy_active": a["efficacy_active"],
                "efficacy_neutral": a["efficacy_neutral"],
                "conditional_amplification_score": a[
                    "conditional_amplification_score"
                ],
            }
            for a in amplifier_entries
        ]
        user_content = (
            f"## 双上下文筛选结果\n"
            f"- active 上下文: {active_ctx}\n"
            f"- neutral 上下文: {neutral_ctx}\n"
            f"- 条件放大器阈值: {threshold}\n"
            f"- 放大器数量: {len(amp_data)}\n\n"
            f"## 放大器数据\n"
            f"{json.dumps(amp_data, ensure_ascii=False, indent=2)}\n\n"
            "请解读这些条件放大器的机制，并按 prompt 约定输出 JSON。"
        )

        messages = [
            {"role": "system", "content": SYSTEM_PROMPTS["dual_context_interpretation"]},
            {"role": "user", "content": user_content},
        ]
        model = self.llm_orchestrator.select_model("deep_insight")

        response = await self.llm_client.chat(messages, model=model)
        content = response.get("content", "")
        usage = response.get("usage", {})

        cost_usd = _estimate_cost(usage, AnalysisTier.DEEP_INSIGHT, model)

        # 解析 LLM 返回的 JSON（容错：解析失败降级为空列表）
        amplifiers: List[Dict[str, Any]] = []
        summary = ""
        try:
            parsed = json.loads(content)
            amplifiers = parsed.get("amplifiers", []) or []
            summary = parsed.get("summary", "") or ""
        except (json.JSONDecodeError, ValueError, TypeError) as e:
            logger.warning(f"LLM 返回 JSON 解析失败，降级为空列表: {e}")
            # 降级：用计算结果填充，mechanism 为空
            amplifiers = [
                {
                    "smiles": a["smiles"],
                    "score": a["conditional_amplification_score"],
                    "mechanism": "",
                }
                for a in amplifier_entries
            ]

        return amplifiers, summary, cost_usd
