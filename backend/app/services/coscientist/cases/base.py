"""Co-Scientist 验证案例适配器基类

基于 Nature 论文中三个验证案例（AML 药物重定位、肝纤维化靶点、AMR 机制）的抽象。
每个案例适配器提供：
1. 案例元数据（名称、描述、研究目标模板、预期基准）
2. 初始假设种子（背景知识，用于 Generation Agent 预热）
3. 验证标准（关键药物/基因/机制列表）
4. 假设评分逻辑（与已知答案的匹配度）
5. 运行后评估（计算 recall/precision）
"""
from abc import ABC, abstractmethod
from typing import Any, Dict, List, Optional


class BaseCaseAdapter(ABC):
    """验证案例适配器抽象基类

    子类必须实现：
    - case_type / name / description / research_goal_template / expected_benchmarks
    - initial_seeds: 初始假设种子列表
    - validation_keywords: 验证关键词
    - get_generation_context(): 返回背景知识文本
    - validate_hypothesis(): 评估单个假设与已知答案的匹配度
    """

    case_type: str = ""
    name: str = ""
    description: str = ""
    research_goal_template: str = ""
    expected_benchmarks: Dict[str, Any] = {}

    # 初始假设种子 — 用于 Generation Agent 的背景提示
    initial_seeds: List[Dict[str, str]] = []

    # 验证关键词 — 用于假设评分时的关键词匹配
    validation_keywords: List[str] = []

    # 目标实体 — 预期出现的药物/基因/机制名称
    target_entities: List[str] = []

    def get_case_info(self) -> Dict[str, Any]:
        """返回案例信息（对应 CaseInfo schema）"""
        return {
            "case_type": self.case_type,
            "name": self.name,
            "description": self.description,
            "research_goal_template": self.research_goal_template,
            "expected_benchmarks": self.expected_benchmarks,
        }

    def get_research_goal(self, custom_goal: Optional[str] = None) -> str:
        """获取研究目标文本

        Args:
            custom_goal: 用户自定义目标（若提供则覆盖模板）
        """
        if custom_goal and len(custom_goal.strip()) >= 10:
            return custom_goal.strip()
        return self.research_goal_template

    def get_initial_seeds(self) -> List[Dict[str, str]]:
        """获取初始假设种子

        Returns:
            [{"name": ..., "description": ..., "mechanism": ...}, ...]
        """
        return self.initial_seeds

    @abstractmethod
    def get_generation_context(self) -> str:
        """返回背景知识文本，用于 Generation Agent 的系统提示

        包含该案例的领域知识、已知机制、关键通路等，
        帮助 LLM 生成更有针对性的初始假设。
        """
        ...

    @abstractmethod
    def validate_hypothesis(self, hypothesis: Dict[str, Any]) -> Dict[str, float]:
        """评估单个假设与已知答案的匹配度

        Args:
            hypothesis: {name, description, mechanism, ...}

        Returns:
            {
                "entity_recall": float,   # 目标实体召回率 0-1
                "keyword_match": float,   # 关键词匹配率 0-1
                "mechanism_alignment": float,  # 机制对齐度 0-1
                "overall_score": float,   # 综合评分 0-1
            }
        """
        ...

    def evaluate_run(
        self,
        hypotheses: List[Dict[str, Any]],
        meta_review: Optional[str] = None,
    ) -> Dict[str, Any]:
        """运行后整体评估

        计算所有假设中是否覆盖了预期目标实体（recall），
        以及生成的假设中有多少匹配了已知答案（precision）。

        Args:
            hypotheses: 排序后的假设列表
            meta_review: Meta-review 报告文本

        Returns:
            {
                "target_entities_found": List[str],
                "target_entities_missed": List[str],
                "recall": float,
                "top_hypothesis_score": float,
                "mean_score": float,
                "meta_review_mentioned_targets": List[str],
                "overall_pass": bool,
            }
        """
        if not hypotheses:
            return {
                "target_entities_found": [],
                "target_entities_missed": list(self.target_entities),
                "recall": 0.0,
                "top_hypothesis_score": 0.0,
                "mean_score": 0.0,
                "meta_review_mentioned_targets": [],
                "overall_pass": False,
            }

        # 逐个评估假设
        scores = []
        all_text = ""
        for hyp in hypotheses:
            score = self.validate_hypothesis(hyp)
            scores.append(score)
            hyp_text = " ".join([
                str(hyp.get("name", "")),
                str(hyp.get("description", "")),
                str(hyp.get("mechanism", "")),
            ])
            all_text += " " + hyp_text

        # 计算目标实体召回
        text_lower = all_text.lower()
        found = []
        missed = []
        for entity in self.target_entities:
            # 支持多别名匹配（entity 可能含 "/" 分隔多个别名）
            aliases = [a.strip().lower() for a in entity.replace("(", "/").replace(")", "/").split("/") if a.strip()]
            if any(a in text_lower for a in aliases):
                found.append(entity)
            else:
                missed.append(entity)

        recall = len(found) / max(len(self.target_entities), 1)

        # Meta-review 中提及的目标实体
        meta_found = []
        if meta_review:
            meta_lower = meta_review.lower()
            for entity in self.target_entities:
                aliases = [a.strip().lower() for a in entity.replace("(", "/").replace(")", "/").split("/") if a.strip()]
                if any(a in meta_lower for a in aliases):
                    meta_found.append(entity)

        # 综合评分
        top_score = max(s["overall_score"] for s in scores)
        mean_score = sum(s["overall_score"] for s in scores) / len(scores)

        # 通过标准：recall >= 0.3 或 top_score >= 0.5
        overall_pass = recall >= 0.3 or top_score >= 0.5

        return {
            "target_entities_found": found,
            "target_entities_missed": missed,
            "recall": round(recall, 4),
            "top_hypothesis_score": round(top_score, 4),
            "mean_score": round(mean_score, 4),
            "meta_review_mentioned_targets": meta_found,
            "overall_pass": overall_pass,
        }

    def _keyword_match_score(self, text: str, keywords: List[str]) -> float:
        """计算关键词匹配率

        Args:
            text: 假设文本
            keywords: 关键词列表

        Returns:
            匹配率 0-1
        """
        if not keywords:
            return 0.0
        text_lower = text.lower()
        matched = sum(1 for kw in keywords if kw.lower() in text_lower)
        return matched / len(keywords)

    def _entity_match_score(self, text: str, entities: List[str]) -> float:
        """计算目标实体匹配率（支持别名）"""
        if not entities:
            return 0.0
        text_lower = text.lower()
        matched = 0
        for entity in entities:
            aliases = [a.strip().lower() for a in entity.replace("(", "/").replace(")", "/").split("/") if a.strip()]
            if any(a in text_lower for a in aliases):
                matched += 1
        return matched / len(entities)
