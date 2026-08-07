"""分级路由测试 — 成本感知分级推理与 IntentRouter 自动档位选择"""
import pytest

from app.core.config import settings
from app.services.intelligence.intent_router import IntentRouter
from app.services.intelligence.orchestrator import UnifiedOrchestrator


class TestLLMTiersConfig:
    """验证 LLM_TIERS 配置正确加载"""

    def test_tiers_exist(self):
        tiers = settings.LLM_TIERS
        assert "turbo" in tiers
        assert "standard" in tiers
        assert "deep" in tiers

    def test_turbo_tier_config(self):
        turbo = settings.LLM_TIERS["turbo"]
        assert turbo["max_rounds"] == 2
        assert turbo["max_initial_count"] == 3
        assert turbo["evidence_level"] == "summary"
        assert turbo["timeout_sec"] == 60

    def test_standard_tier_config(self):
        standard = settings.LLM_TIERS["standard"]
        assert standard["max_rounds"] == 3
        assert standard["max_initial_count"] == 5
        assert standard["evidence_level"] == "compact"
        assert standard["timeout_sec"] == 300

    def test_deep_tier_config(self):
        deep = settings.LLM_TIERS["deep"]
        assert deep["max_rounds"] == 3
        assert deep["max_initial_count"] == 4
        assert deep["evidence_level"] == "full"
        assert deep["timeout_sec"] == 600

    def test_default_tier(self):
        assert settings.DEFAULT_LLM_TIER == "standard"

    def test_tiers_have_descriptions(self):
        for name, config in settings.LLM_TIERS.items():
            assert "description" in config
            assert len(config["description"]) > 0


class TestIntentRouterSuggestTier:
    """测试 IntentRouter.suggest_tier 档位推荐"""

    def setup_method(self):
        self.router = IntentRouter(llm_client=None)

    def test_force_tier_takes_precedence(self):
        tier = self.router.suggest_tier(
            message="简单问题",
            intent_mode="reasoning",
            intent_confidence=0.95,
            force_tier="turbo",
        )
        assert tier == "turbo"

    def test_force_tier_auto_ignored(self):
        tier = self.router.suggest_tier(
            message="简单问题",
            intent_mode="chat",
            intent_confidence=0.3,
            force_tier="auto",
        )
        assert tier == "turbo"

    def test_reasoning_high_confidence_deep(self):
        msg = (
            "请深度分析 EGFR 靶点的机制通路信号转导并生成假设，"
            "同时设计优化方案并且验证通路信号，此外还需要分析靶点的表达水平"
        )
        tier = self.router.suggest_tier(
            message=msg,
            intent_mode="reasoning",
            intent_confidence=0.95,
            force_tier=None,
        )
        assert tier == "deep"

    def test_reasoning_medium_confidence_standard(self):
        tier = self.router.suggest_tier(
            message="分析一下这个靶点",
            intent_mode="reasoning",
            intent_confidence=0.7,
            force_tier=None,
        )
        assert tier == "standard"

    def test_agent_mode_standard(self):
        tier = self.router.suggest_tier(
            message="搜索 EGFR 相关文献",
            intent_mode="agent",
            intent_confidence=0.8,
            force_tier=None,
        )
        assert tier == "standard"

    def test_chat_mode_turbo(self):
        tier = self.router.suggest_tier(
            message="什么是 EGFR?",
            intent_mode="chat",
            intent_confidence=0.9,
            force_tier=None,
        )
        assert tier == "turbo"

    def test_hybrid_high_confidence_deep(self):
        msg = (
            "分析靶点机制并生成假设，同时设计优化方案以验证通路信号，"
            "此外还需要深度评估靶点的表达水平并且预测治疗效果"
        )
        tier = self.router.suggest_tier(
            message=msg,
            intent_mode="hybrid",
            intent_confidence=0.9,
            force_tier=None,
        )
        assert tier == "deep"


class TestComplexityEstimation:
    """测试消息复杂度估算"""

    def setup_method(self):
        self.router = IntentRouter(llm_client=None)

    def test_short_simple_message(self):
        score = IntentRouter._estimate_complexity("什么是 EGFR?")
        assert score < 0.3

    def test_long_message(self):
        long_msg = "EGFR 靶点 " * 50
        score = IntentRouter._estimate_complexity(long_msg)
        assert score > 0.2

    def test_multiple_questions(self):
        msg = "EGFR 是什么？它在癌症中的作用是什么？如何靶向治疗？预后如何？"
        score = IntentRouter._estimate_complexity(msg)
        assert score > 0.2

    def test_domain_terms(self):
        msg = "分析靶点机制通路信号转导并设计优化方案"
        score = IntentRouter._estimate_complexity(msg)
        assert score > 0.1

    def test_empty_message(self):
        score = IntentRouter._estimate_complexity("")
        assert score == 0.0

    def test_multi_part_message(self):
        msg = "分析 EGFR 并且设计方案同时验证靶点以及优化通路"
        score = IntentRouter._estimate_complexity(msg)
        assert score > 0.2


class TestOrchestratorTierResolution:
    """测试 UnifiedOrchestrator 的档位解析"""

    def _create_orchestrator(self):
        from unittest.mock import MagicMock, AsyncMock
        db = MagicMock()
        llm_client = MagicMock()
        llm_client.chat = AsyncMock(return_value={"content": "test", "usage": {}, "model": "mock"})
        orch = UnifiedOrchestrator(db=db, llm_client=llm_client)
        return orch

    def test_get_tier_config_valid(self):
        orch = self._create_orchestrator()
        config = orch._get_tier_config("turbo")
        assert config["max_rounds"] == 2
        assert config["evidence_level"] == "summary"
        assert config["timeout_sec"] == 60

    def test_get_tier_config_unknown_defaults(self):
        orch = self._create_orchestrator()
        config = orch._get_tier_config("nonexistent")
        assert config == settings.LLM_TIERS["standard"]

    def test_resolve_tier_user_specified(self):
        orch = self._create_orchestrator()
        tier = orch._resolve_tier(
            tier="deep",
            message="分析靶点",
            intent_mode="chat",
            intent_confidence=0.3,
        )
        assert tier == "deep"

    def test_resolve_tier_user_invalid_fallback(self):
        orch = self._create_orchestrator()
        tier = orch._resolve_tier(
            tier="invalid_tier",
            message="分析靶点",
            intent_mode="chat",
            intent_confidence=0.3,
        )
        assert tier == "turbo"

    def test_resolve_tier_auto_reasoning_deep(self):
        orch = self._create_orchestrator()
        tier = orch._resolve_tier(
            tier=None,
            message="深度分析 EGFR 靶点的机制",
            intent_mode="reasoning",
            intent_confidence=0.9,
        )
        assert tier == "deep"

    def test_resolve_tier_auto_reasoning_standard(self):
        orch = self._create_orchestrator()
        tier = orch._resolve_tier(
            tier=None,
            message="分析靶点",
            intent_mode="reasoning",
            intent_confidence=0.6,
        )
        assert tier == "standard"

    def test_resolve_tier_auto_chat_turbo(self):
        orch = self._create_orchestrator()
        tier = orch._resolve_tier(
            tier=None,
            message="什么是 EGFR?",
            intent_mode="chat",
            intent_confidence=0.9,
        )
        assert tier == "turbo"

    def test_resolve_tier_auto_agent_standard(self):
        orch = self._create_orchestrator()
        tier = orch._resolve_tier(
            tier=None,
            message="搜索文献",
            intent_mode="agent",
            intent_confidence=0.8,
        )
        assert tier == "standard"

    def test_resolve_tier_auto_hybrid_deep(self):
        orch = self._create_orchestrator()
        tier = orch._resolve_tier(
            tier=None,
            message="分析并生成假设",
            intent_mode="hybrid",
            intent_confidence=0.9,
        )
        assert tier == "deep"


class TestTierIntegration:
    """档位集成测试 — 验证配置传递一致性"""

    def test_tier_config_consistency(self):
        for tier_name in ["turbo", "standard", "deep"]:
            config = settings.LLM_TIERS[tier_name]
            assert isinstance(config["max_rounds"], int)
            assert isinstance(config["timeout_sec"], int)
            assert config["max_rounds"] >= 1
            assert config["timeout_sec"] > 0
            assert config["evidence_level"] in ("summary", "compact", "full")

    def test_tier_timeout_ordering(self):
        turbo = settings.LLM_TIERS["turbo"]["timeout_sec"]
        standard = settings.LLM_TIERS["standard"]["timeout_sec"]
        deep = settings.LLM_TIERS["deep"]["timeout_sec"]
        assert turbo < standard < deep

    def test_tier_rounds_ordering(self):
        turbo = settings.LLM_TIERS["turbo"]["max_rounds"]
        standard = settings.LLM_TIERS["standard"]["max_rounds"]
        assert turbo <= standard

    def test_suggest_tier_returns_valid_tier(self):
        router = IntentRouter(llm_client=None)
        for mode in ["chat", "reasoning", "agent", "hybrid"]:
            tier = router.suggest_tier("test message", mode, 0.5)
            assert tier in ("turbo", "standard", "deep")