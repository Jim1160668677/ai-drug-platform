"""测试 LLM Prompts 扩展 — 验证 5 个新 SYSTEM_PROMPTS 存在且内容符合契约

覆盖 Phase 2.5 任务：
- hybrid_hypothesis / hybrid_reranking / hybrid_report
- vaccine_design / dual_context_interpretation
"""
import pytest

from app.services.llm.prompts import SYSTEM_PROMPTS


class TestHybridPrompts:
    """验证 5 个新 SYSTEM_PROMPTS 的存在性与结构化契约"""

    def test_5_new_prompts_exist(self):
        """5 个新 prompt 必须全部在 SYSTEM_PROMPTS 字典中"""
        required = {
            "hybrid_hypothesis",
            "hybrid_reranking",
            "hybrid_report",
            "vaccine_design",
            "dual_context_interpretation",
        }
        missing = required - set(SYSTEM_PROMPTS.keys())
        assert not missing, f"缺失 prompt: {missing}"
        # 至少 7 个（2 既有 + 5 新）
        assert len(SYSTEM_PROMPTS) >= 7

    def test_hybrid_hypothesis_has_role(self):
        """hybrid_hypothesis 必须包含「假设」或「筛选」角色定义"""
        prompt = SYSTEM_PROMPTS["hybrid_hypothesis"]
        assert "假设" in prompt or "筛选" in prompt
        # 必须输出 JSON
        assert "JSON" in prompt or "json" in prompt
        # 必须提及候选分子
        assert "候选" in prompt or "SMILES" in prompt

    def test_hybrid_reranking_has_criteria(self):
        """hybrid_reranking 必须包含对接分数 + 药化知识要素"""
        prompt = SYSTEM_PROMPTS["hybrid_reranking"]
        # 对接分数
        assert "对接" in prompt or "affinity" in prompt.lower() or "RMSD" in prompt
        # 药化知识（毒理/相互作用）
        assert "毒" in prompt or "相互作用" in prompt or "药化" in prompt
        # 输出 JSON
        assert "JSON" in prompt or "json" in prompt

    def test_hybrid_report_has_cost_section(self):
        """hybrid_report 必须包含成本节省/效益要素"""
        prompt = SYSTEM_PROMPTS["hybrid_report"]
        # 成本要素
        assert "成本" in prompt or "cost" in prompt.lower()
        # 节省百分比
        assert "节省" in prompt or "saving" in prompt.lower()
        # Markdown 输出
        assert "Markdown" in prompt or "markdown" in prompt

    def test_vaccine_design_has_gc_constraint(self):
        """vaccine_design 必须包含 GC 含量 30-70% 约束"""
        prompt = SYSTEM_PROMPTS["vaccine_design"]
        # GC 含量约束
        assert "GC" in prompt or "gc_content" in prompt
        # 30-70 范围
        assert "30" in prompt and "70" in prompt
        # mRNA 长度约束
        assert "mRNA" in prompt or "mRNA" in prompt

    def test_dual_context_interpretation_has_amplifier(self):
        """dual_context_interpretation 必须包含条件放大器概念"""
        prompt = SYSTEM_PROMPTS["dual_context_interpretation"]
        # 条件放大器
        assert "放大器" in prompt or "amplifier" in prompt.lower()
        # 双上下文
        assert "上下文" in prompt or "context" in prompt.lower()
        # conditional_amplification_score
        assert (
            "conditional_amplification_score" in prompt
            or "amplification_score" in prompt
        )
