"""AnalysisService — 统一解读模块（标准化数据处理与分析流程）

设计来源：方向 A（管道嵌入+追溯）— 将 LLMOrchestrator.full_analysis 中
分散的分析-解读-报告生成逻辑提炼为独立服务，提供一致的数据解读接口。

核心能力：
1. interpret：通用解读入口 — 输入分析数据 + 上下文，输出结构化解读（结论/假设/建议）
2. analyze_dataset：数据集解读 — 从 Dataset.parsed_summary 提取分析结果并解读
3. interpret_evidence：证据解读 — 基于 EvidenceBundle 生成综合解读报告
4. 标准化流程：数据校验 → 证据收集 → LLM 解读 → 结构化输出 → 追溯记录

与大模型协作：LLM 作为「大脑」解读分析数据，本服务作为编排层统一调度。
"""
import json
import logging
import time
from typing import Any, Dict, List, Optional
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.services.intelligence.evidence_collector import EvidenceBundle, EvidenceCollector

logger = logging.getLogger(__name__)


# ========== 意图识别（轻量关键词路由，复用 orchestrator 模式） ==========

_INTENT_KEYWORDS: Dict[str, List[str]] = {
    "target_discovery": ["靶点", "发现靶点", "target", "discover", "驱动基因", "差异基因"],
    "drug_repurposing": ["老药", "重定位", "repurpose", "已上市", "再利用"],
    "pathway_analysis": ["通路", "富集", "pathway", "enrichment", "kegg", "go term"],
    "molecule_design": ["分子", "设计", "molecule", "smiles", "类药", "先导"],
    "experiment_validation": ["实验", "验证", "experiment", "抑制率", "疗效", "recist"],
    "genome_interpretation": ["基因组", "风险", "位点", "genotype", "snp", "性状"],
    "data_exploration": ["数据", "分布", "聚类", "cluster", "降维", "umap", "tsne"],
}


def _detect_intent(message: str) -> str:
    """基于关键词的轻量意图识别"""
    msg_lower = message.lower()
    for intent, keywords in _INTENT_KEYWORDS.items():
        if any(kw in msg_lower for kw in keywords):
            return intent
    return "general_analysis"


# ========== 解读结果数据结构 ==========

class InterpretationResult:
    """解读结果（字典化输出，便于 API 序列化）"""

    def __init__(
        self,
        intent: str,
        conclusion: str,
        hypothesis: str,
        recommendations: List[str],
        key_findings: List[str],
        model: str,
        cost_usd: float,
        duration_sec: float,
        evidence_summary: Optional[Dict[str, Any]] = None,
    ):
        self.intent = intent
        self.conclusion = conclusion
        self.hypothesis = hypothesis
        self.recommendations = recommendations
        self.key_findings = key_findings
        self.model = model
        self.cost_usd = cost_usd
        self.duration_sec = duration_sec
        self.evidence_summary = evidence_summary

    def to_dict(self) -> Dict[str, Any]:
        return {
            "intent": self.intent,
            "conclusion": self.conclusion,
            "hypothesis": self.hypothesis,
            "recommendations": self.recommendations,
            "key_findings": self.key_findings,
            "model": self.model,
            "cost_usd": self.cost_usd,
            "duration_sec": self.duration_sec,
            "evidence_summary": self.evidence_summary,
        }


class AnalysisService:
    """统一解读服务 — 标准化数据处理与分析流程

    用法：
        svc = AnalysisService(db, llm_client)
        result = await svc.interpret(
            message="分析 EGFR 靶点的功能",
            analysis_data={"targets": [...]},
            project_id="...",
        )
    """

    def __init__(
        self,
        db: Optional[AsyncSession] = None,
        llm_client: Any = None,
        trace_store: Optional[Any] = None,
    ):
        self.db = db
        self.llm_client = llm_client
        self.trace_store = trace_store
        self.evidence_collector = EvidenceCollector(db=db)

    # ========== 通用解读入口 ==========

    async def interpret(
        self,
        message: str,
        analysis_data: Optional[Dict[str, Any]] = None,
        project_id: Optional[str] = None,
        intent: Optional[str] = None,
        session_id: Optional[UUID] = None,
        run_id: Optional[UUID] = None,
    ) -> Dict[str, Any]:
        """通用解读入口 — 数据校验 → 证据收集 → LLM 解读 → 结构化输出

        Args:
            message: 用户问题/分析目标
            analysis_data: 已有分析数据（可选，无则从项目证据收集）
            project_id: 项目 ID（可选，用于收集补充证据）
            intent: 指定意图（可选，None 时自动识别）
            session_id: 会话 ID（追溯用）
            run_id: 运行 ID（追溯用）

        Returns:
            InterpretationResult.to_dict()
        """
        start = time.time()
        detected_intent = intent or _detect_intent(message)
        model = settings.LLM_MODEL_DEEP

        # 1. 组装分析上下文
        evidence_summary: Optional[Dict[str, Any]] = None
        context_text = ""
        if analysis_data:
            context_text = self._format_analysis_data(analysis_data, detected_intent)
        elif project_id:
            bundle = await self.evidence_collector.collect_project_evidence_bundle(project_id)
            context_text = bundle.text
            evidence_summary = bundle.to_dict()

        # 2. 构建 LLM 提示词
        prompt = self._build_interpretation_prompt(message, detected_intent, context_text)
        messages = [
            {"role": "system", "content": self._system_prompt(detected_intent)},
            {"role": "user", "content": prompt},
        ]

        # 3. 调用 LLM 解读
        cost_usd = 0.0
        raw_text = ""
        try:
            if self.llm_client is not None:
                response = await self.llm_client.chat(messages, model=model)
                raw_text = response.get("content", "") if isinstance(response, dict) else str(response)
                usage = response.get("usage", {}) if isinstance(response, dict) else {}
                cost_usd = self._estimate_cost(usage, model)
            else:
                raw_text = "（LLM 客户端未注入，跳过解读）"
        except Exception as e:
            logger.error("[AnalysisService] LLM 解读失败: %s", e)
            raw_text = f"解读过程中出现错误：{str(e)}"

        # 4. 结构化解析 LLM 输出
        conclusion, hypothesis, recommendations, key_findings = self._parse_interpretation(raw_text)

        duration_sec = round(time.time() - start, 3)

        # 5. 写追溯
        if self.trace_store is not None:
            try:
                await self.trace_store.append(
                    step_type="analysis_interpretation",
                    run_id=run_id, session_id=session_id,
                    agent_name="analysis_service",
                    input_data={"intent": detected_intent, "message": message[:300]},
                    output_data={"conclusion": conclusion[:300]},
                    cost_usd=cost_usd, duration_sec=duration_sec,
                )
            except Exception as e:
                logger.warning("[AnalysisService] 写追溯失败: %s", e)

        result = InterpretationResult(
            intent=detected_intent,
            conclusion=conclusion,
            hypothesis=hypothesis,
            recommendations=recommendations,
            key_findings=key_findings,
            model=model,
            cost_usd=cost_usd,
            duration_sec=duration_sec,
            evidence_summary=evidence_summary,
        )
        return result.to_dict()

    # ========== 数据集解读 ==========

    async def analyze_dataset(
        self,
        dataset_id: str,
        message: Optional[str] = None,
        project_id: Optional[str] = None,
        session_id: Optional[UUID] = None,
    ) -> Dict[str, Any]:
        """数据集解读 — 从 Dataset.parsed_summary 提取分析结果并解读

        Args:
            dataset_id: 数据集 ID
            message: 解读方向（可选，默认基于数据类型）
            project_id: 项目 ID（可选，补充项目上下文）
            session_id: 会话 ID（追溯用）
        """
        from app.db.session import async_session_factory
        from app.models.dataset import Dataset

        analysis_data: Dict[str, Any] = {}
        try:
            if self.db is not None:
                ds = await self.db.get(Dataset, UUID(dataset_id))
            else:
                async with async_session_factory() as db:
                    ds = await db.get(Dataset, UUID(dataset_id))
            if ds:
                analysis_data = {
                    "dataset_name": ds.name,
                    "data_type": ds.data_type,
                    "parsed_summary": ds.parsed_summary or {},
                }
                if not project_id and ds.project_id:
                    project_id = str(ds.project_id)
        except Exception as e:
            logger.warning("[AnalysisService] 加载数据集失败: %s", e)

        if not analysis_data:
            return {"error": "数据集不存在或无分析结果", "dataset_id": dataset_id}

        goal = message or f"解读数据集 {analysis_data.get('dataset_name', '')} 的分析结果，提炼关键发现与下一步建议"
        return await self.interpret(
            message=goal,
            analysis_data=analysis_data,
            project_id=project_id,
            intent=_detect_intent(analysis_data.get("data_type", "")),
            session_id=session_id,
        )

    # ========== 证据解读 ==========

    async def interpret_evidence(
        self,
        bundle: EvidenceBundle,
        message: str = "基于收集的项目证据进行综合解读",
        session_id: Optional[UUID] = None,
        run_id: Optional[UUID] = None,
    ) -> Dict[str, Any]:
        """基于 EvidenceBundle 生成综合解读报告"""
        analysis_data = {"evidence_bundle": bundle.to_dict(), "structured": bundle.structured}
        return await self.interpret(
            message=message,
            analysis_data=analysis_data,
            project_id=bundle.project_id,
            session_id=session_id,
            run_id=run_id,
        )

    # ========== 私有方法 ==========

    def _system_prompt(self, intent: str) -> str:
        return (
            "你是 AI 模式精准药物设计系统的数据分析解读专家。"
            f"当前分析意图：{intent}。"
            "请基于提供的分析数据，输出结构化解读，包含：\n"
            "1. 【结论】用 2-3 句话概括核心发现\n"
            "2. 【假设】提出 1 个可验证的科学假设\n"
            "3. 【建议】列出 2-3 条下一步研究建议（用 - 开头）\n"
            "4. 【关键发现】列出 3-5 条关键发现（用 - 开头）\n"
            "请严格遵循上述四个章节标题，便于结构化解析。"
        )

    def _build_interpretation_prompt(
        self, message: str, intent: str, context_text: str,
    ) -> str:
        parts = [f"## 用户问题\n{message}"]
        if context_text:
            parts.append(f"## 分析数据/项目证据\n{context_text[:6000]}")
        parts.append("请基于上述信息进行结构化解读。")
        return "\n\n".join(parts)

    def _format_analysis_data(self, data: Dict[str, Any], intent: str) -> str:
        """将分析数据格式化为文本上下文"""
        try:
            return json.dumps(data, ensure_ascii=False, default=str)[:6000]
        except Exception:
            return str(data)[:6000]

    def _parse_interpretation(self, text: str) -> tuple:
        """解析 LLM 输出为 (结论, 假设, 建议, 关键发现)"""
        conclusion = ""
        hypothesis = ""
        recommendations: List[str] = []
        key_findings: List[str] = []

        current_section = None
        for line in text.split("\n"):
            stripped = line.strip()
            if "【结论】" in stripped or stripped.startswith("结论"):
                current_section = "conclusion"
                conclusion = stripped.split("】")[-1].split("：")[-1].strip() if "】" in stripped or "：" in stripped else ""
                if not conclusion:
                    conclusion = stripped.replace("【结论】", "").replace("结论：", "").replace("结论:", "").strip()
            elif "【假设】" in stripped or stripped.startswith("假设"):
                current_section = "hypothesis"
                hypothesis = stripped.replace("【假设】", "").replace("假设：", "").replace("假设:", "").strip()
            elif "【建议】" in stripped or stripped.startswith("建议"):
                current_section = "recommendations"
                continue
            elif "【关键发现】" in stripped or stripped.startswith("关键发现"):
                current_section = "key_findings"
                continue
            elif stripped.startswith("-"):
                item = stripped.lstrip("- ").strip()
                if current_section == "recommendations" and item:
                    recommendations.append(item)
                elif current_section == "key_findings" and item:
                    key_findings.append(item)
            elif current_section == "conclusion" and stripped and not conclusion:
                conclusion = stripped

        # 兜底：若未解析到结论，用原文前 300 字
        if not conclusion and text:
            conclusion = text[:300]
        if not hypothesis:
            hypothesis = "（未提取到明确假设）"

        return conclusion, hypothesis, recommendations, key_findings

    def _estimate_cost(self, usage: Dict[str, Any], model: str) -> float:
        """估算 LLM 调用成本（美元）"""
        if not usage:
            return 0.0
        prompt_tokens = usage.get("prompt_tokens", 0)
        completion_tokens = usage.get("completion_tokens", 0)
        # 粗略定价：输入 $0.5/1M，输出 $1.5/1M
        return round((prompt_tokens * 0.5 + completion_tokens * 1.5) / 1_000_000, 6)


class _NullCtx:
    """空上下文管理器（保留兼容，已不再使用）"""
    async def __aenter__(self):
        return None
    async def __aexit__(self, *args):
        return False


__all__ = ["AnalysisService", "InterpretationResult", "_detect_intent"]
