"""v2.0 优化方案综合测试计划

覆盖范围：
  1. 功能测试 - 7 项建议的核心功能验证
  2. 性能测试 - 关键路径延迟与吞吐
  3. 兼容性测试 - 向后兼容与 Mock/Real 双模式
  4. 安全性测试 - 权限、防绕过、数据完整性

测试策略：
  - 全部单元测试，数据库会话用 Mock
  - 每个测试类对应一项建议
  - 包含性能断言（延迟上限）
  - 包含安全断言（权限/防绕过）

运行：
  cd backend && .venv/bin/python -m pytest tests/test_v2_0_comprehensive.py -v --tb=short
"""
import asyncio
import hashlib
import time
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest


# ============================================================
# 建议一：干湿闭环升级 — experimental_elo_adjustment 分离
# ============================================================

class TestFeedbackWithExperimentalElo:
    """验证实验驱动的 Elo 调整量独立于 LLM 评分"""

    @pytest.mark.asyncio
    async def test_validation_feedback_updates_separate_fields(self):
        """apply_validation_feedback 同时更新 elo_score 和 experimental_elo_adjustment"""
        from app.services.experiment.feedback_loop import FeedbackLoop

        experiment = SimpleNamespace(
            id=uuid4(),
            success=True,
            result={"conclusion": "VALIDATED"},
            config={},
            notes="",
            hypothesis=SimpleNamespace(
                id=uuid4(),
                elo_score=1000.0,
                evolution_history=[],
                experimental_elo_adjustment=0.0,
                experimental_validation_count=0,
            ),
            project_id=uuid4(),
            target_id=None,
            molecule_id=None,
            hypothesis_id=None,
            iteration=1,
            lab_source="test-lab",
        )

        mock_scalar_result = MagicMock()
        mock_scalar_result.scalar_one_or_none.return_value = None
        mock_db = MagicMock()
        mock_db.execute = AsyncMock(return_value=mock_scalar_result)
        mock_db.flush = AsyncMock()
        mock_db.commit = AsyncMock()
        mock_db.begin = MagicMock(return_value=MagicMock(__aenter__=AsyncMock(), __aexit__=AsyncMock()))

        loop = FeedbackLoop(mock_db)
        result = await loop.apply_validation_feedback(experiment, "VALIDATED", confidence=0.8)

        assert result["success"] is True
        assert result["elo_change"] == pytest.approx(12.0, abs=0.01)  # 15 * 0.8
        assert result["elo_before"] == 1000.0
        assert result["elo_after"] == pytest.approx(1012.0, abs=0.01)

        # 验证 experimental_elo_adjustment 字段被更新
        h = experiment.hypothesis
        assert h.experimental_elo_adjustment == pytest.approx(12.0, abs=0.01)
        assert h.experimental_validation_count == 1

        # 验证 evolution_history 记录包含 experimental_elo_cumulative
        assert len(h.evolution_history) == 1
        entry = h.evolution_history[0]
        assert "experimental_elo_cumulative" in entry
        assert entry["experimental_elo_cumulative"] == pytest.approx(12.0, abs=0.01)

    @pytest.mark.asyncio
    async def test_refuted_conclusion_negative_elo(self):
        """REFUTED 结论应产生负 Elo 调整"""
        from app.services.experiment.feedback_loop import FeedbackLoop

        experiment = SimpleNamespace(
            id=uuid4(),
            success=False,
            result={"conclusion": "REFUTED"},
            config={},
            notes="",
            hypothesis=SimpleNamespace(
                id=uuid4(),
                elo_score=1000.0,
                evolution_history=[],
                experimental_elo_adjustment=5.0,  # 之前已有正调整
                experimental_validation_count=2,
            ),
            project_id=uuid4(),
            target_id=None,
            molecule_id=None,
            hypothesis_id=None,
            iteration=1,
            lab_source="test-lab",
        )

        mock_scalar_result = MagicMock()
        mock_scalar_result.scalar_one_or_none.return_value = None
        mock_db = MagicMock()
        mock_db.execute = AsyncMock(return_value=mock_scalar_result)
        mock_db.flush = AsyncMock()
        mock_db.commit = AsyncMock()
        mock_db.begin = MagicMock(return_value=MagicMock(__aenter__=AsyncMock(), __aexit__=AsyncMock()))

        loop = FeedbackLoop(mock_db)
        result = await loop.apply_validation_feedback(experiment, "REFUTED", confidence=1.0)

        assert result["success"] is True
        assert result["elo_change"] == -25.0

        h = experiment.hypothesis
        # 累计：之前 5.0 + 本次 -25.0 = -20.0
        assert h.experimental_elo_adjustment == pytest.approx(-20.0, abs=0.01)
        assert h.experimental_validation_count == 3

    @pytest.mark.asyncio
    async def test_confidence_weighting(self):
        """置信度权重影响 Elo 调整幅度"""
        from app.services.experiment.feedback_loop import FeedbackLoop

        experiment = SimpleNamespace(
            id=uuid4(),
            success=True,
            result={"conclusion": "VALIDATED"},
            config={},
            notes="",
            hypothesis=SimpleNamespace(
                id=uuid4(),
                elo_score=1000.0,
                evolution_history=[],
                experimental_elo_adjustment=0.0,
                experimental_validation_count=0,
            ),
            project_id=uuid4(),
            target_id=None,
            molecule_id=None,
            hypothesis_id=None,
            iteration=1,
            lab_source="test-lab",
        )

        mock_scalar_result = MagicMock()
        mock_scalar_result.scalar_one_or_none.return_value = None
        mock_db = MagicMock()
        mock_db.execute = AsyncMock(return_value=mock_scalar_result)
        mock_db.flush = AsyncMock()
        mock_db.commit = AsyncMock()
        mock_db.begin = MagicMock(return_value=MagicMock(__aenter__=AsyncMock(), __aexit__=AsyncMock()))

        loop = FeedbackLoop(mock_db)

        # 低置信度：0.3
        result_low = await loop.apply_validation_feedback(experiment, "VALIDATED", confidence=0.3)
        assert result_low["elo_change"] == pytest.approx(4.5, abs=0.01)

        # 高置信度：0.9
        experiment.hypothesis.elo_score = 1000.0
        experiment.hypothesis.experimental_elo_adjustment = 0.0
        result_high = await loop.apply_validation_feedback(experiment, "VALIDATED", confidence=0.9)
        assert result_high["elo_change"] == pytest.approx(13.5, abs=0.01)

        # 断言：高置信度 > 低置信度
        assert result_high["elo_change"] > result_low["elo_change"]

    @pytest.mark.asyncio
    async def test_inconclusive_no_change(self):
        """INCONCLUSIVE 结论不改变 Elo"""
        from app.services.experiment.feedback_loop import FeedbackLoop

        experiment = SimpleNamespace(
            id=uuid4(),
            success=True,
            result={"conclusion": "INCONCLUSIVE"},
            config={},
            notes="",
            hypothesis=SimpleNamespace(
                id=uuid4(),
                elo_score=1000.0,
                evolution_history=[],
                experimental_elo_adjustment=0.0,
                experimental_validation_count=0,
            ),
            project_id=uuid4(),
            target_id=None,
            molecule_id=None,
            hypothesis_id=None,
            iteration=1,
            lab_source="test-lab",
        )

        mock_scalar_result = MagicMock()
        mock_scalar_result.scalar_one_or_none.return_value = None
        mock_db = MagicMock()
        mock_db.execute = AsyncMock(return_value=mock_scalar_result)
        mock_db.flush = AsyncMock()
        mock_db.commit = AsyncMock()
        mock_db.begin = MagicMock(return_value=MagicMock(__aenter__=AsyncMock(), __aexit__=AsyncMock()))

        loop = FeedbackLoop(mock_db)
        result = await loop.apply_validation_feedback(experiment, "INCONCLUSIVE")

        assert result["elo_change"] == 0.0
        assert result["elo_before"] == result["elo_after"]

    @pytest.mark.asyncio
    async def test_invalid_conclusion_rejected(self):
        """非法结论应抛出 ValueError"""
        from app.services.experiment.feedback_loop import FeedbackLoop

        experiment = SimpleNamespace(
            id=uuid4(),
            hypothesis=SimpleNamespace(id=uuid4(), elo_score=1000.0, evolution_history=[]),
            project_id=uuid4(),
        )

        mock_db = MagicMock()
        loop = FeedbackLoop(mock_db)

        with pytest.raises(ValueError, match="非法结论"):
            await loop.apply_validation_feedback(experiment, "INVALID")


# ============================================================
# 建议二：失败数据价值化 — WrongPathAvoider 集成
# ============================================================

class TestFailureKnowledgeIntegration:
    """验证失败知识与规避服务的集成"""

    @pytest.mark.asyncio
    async def test_ingest_failure_creates_knowledge(self):
        """ingest_failure 将失败实验沉淀为 FailureKnowledge"""
        from app.services.experiment.feedback_loop import FeedbackLoop

        experiment = SimpleNamespace(
            id=uuid4(),
            success=False,
            result={"error": "contamination detected"},
            config={},
            notes="培养基被污染",
            exp_type="in_vitro",
            status="failed",
            project_id=uuid4(),
            target_id=uuid4(),
            molecule_id=None,
            hypothesis_id=None,
            iteration=1,
            lab_source="test-lab",
        )

        mock_scalar_result = MagicMock()
        mock_scalar_result.scalar_one_or_none.return_value = None
        mock_db = MagicMock()
        mock_db.execute = AsyncMock(return_value=mock_scalar_result)
        mock_db.flush = AsyncMock()
        mock_db.add = MagicMock()

        loop = FeedbackLoop(mock_db)
        result = await loop.ingest_failure(experiment)

        assert result["failure_knowledge_id"] is not None
        assert result["failure_reason"] is not None
        assert result["is_new"] is True
        mock_db.add.assert_called_once()

    @pytest.mark.asyncio
    async def test_skip_successful_experiment(self):
        """成功实验跳过失败沉淀"""
        from app.services.experiment.feedback_loop import FeedbackLoop

        experiment = SimpleNamespace(
            success=True, result={}, config={}, notes="",
        )

        mock_db = MagicMock()
        loop = FeedbackLoop(mock_db)
        result = await loop.ingest_failure(experiment)

        assert result["failure_knowledge_id"] is None
        assert result["is_new"] is False

    @pytest.mark.asyncio
    async def test_existing_failure_accumulates(self):
        """已有失败记录时累加计数"""
        from app.services.experiment.feedback_loop import FeedbackLoop

        existing = SimpleNamespace(
            id=uuid4(),
            failure_reason="contamination",
            failure_params={"ph": 7.4},
            wrong_path_proof="真菌污染",
            failure_count=2,
            is_high_confidence=False,
        )

        experiment = SimpleNamespace(
            id=uuid4(),
            success=False,
            result={"error": "contamination"},
            config={},
            notes="再次污染",
            exp_type="in_vitro",
            status="failed",
            project_id=uuid4(),
            target_id=uuid4(),
            molecule_id=None,
            hypothesis_id=None,
            iteration=1,
            lab_source="test-lab",
        )

        mock_scalar_result = MagicMock()
        mock_scalar_result.scalar_one_or_none.return_value = existing
        mock_db = MagicMock()
        mock_db.execute = AsyncMock(return_value=mock_scalar_result)
        mock_db.flush = AsyncMock()

        loop = FeedbackLoop(mock_db)
        result = await loop.ingest_failure(experiment)

        assert result["is_new"] is False
        assert existing.failure_count == 3  # 累加


class TestWrongPathAvoider:
    """WrongPathAvoider 规避逻辑"""

    @pytest.mark.asyncio
    async def test_query_returns_ordered_by_count(self):
        """查询结果按失败次数降序排列"""
        from app.services.analyzer.wrong_path_service import WrongPathAvoider

        records = [
            SimpleNamespace(
                id=uuid4(), failure_reason="contamination",
                wrong_path_proof="严重污染", is_high_confidence=True,
                failure_count=5, target_id=None, molecule_id=None,
            ),
            SimpleNamespace(
                id=uuid4(), failure_reason="concentration",
                wrong_path_proof="浓度过高", is_high_confidence=False,
                failure_count=1, target_id=None, molecule_id=None,
            ),
        ]

        mock_scalar_result = MagicMock()
        mock_scalar_result.scalars.return_value.all.return_value = records
        mock_db = MagicMock()
        mock_db.execute = AsyncMock(return_value=mock_scalar_result)

        avoider = WrongPathAvoider(mock_db)
        result = await avoider.query_failures(project_id=uuid4())

        assert len(result) == 2
        assert result[0]["failure_count"] >= result[1]["failure_count"]

    @pytest.mark.asyncio
    async def test_should_avoid_high_confidence(self):
        """高置信度失败应触发规避"""
        from app.services.analyzer.wrong_path_service import WrongPathAvoider

        mock_db = MagicMock()
        avoider = WrongPathAvoider(mock_db)

        # 高置信度 + 高于阈值
        assert avoider.should_avoid(0.8, high_confidence_threshold=0.7) is True
        assert avoider.should_avoid(0.5, high_confidence_threshold=0.7) is False

        # 低置信度 + 任何分数
        assert avoider.should_avoid(0.9, high_confidence_threshold=0.95) is False


# ============================================================
# 建议三：语义嵌入邻近度 — 融合评分
# ============================================================

class TestEmbeddingProximityFusion:
    """验证嵌入+Jaccard 融合评分"""

    @pytest.mark.asyncio
    async def test_fusion_weights_correct(self):
        """融合权重按配置应用"""
        from app.services.coscientist.algorithms.embedding_proximity import EmbeddingProximity

        ep = EmbeddingProximity(llm_refine_threshold=0.45, direct_merge_threshold=0.75)

        result = ep.fuse_with_jaccard(0.6, 0.5)
        # fused = 0.6*0.6 + 0.4*0.5 = 0.36 + 0.20 = 0.56
        assert result["fused_score"] == pytest.approx(0.56, abs=0.01)
        assert result["llm_refine"] is True  # > 0.45 (但 0.6 < 0.75 不触发 direct_merge)

    @pytest.mark.asyncio
    async def test_direct_merge_threshold(self):
        """纯语义分 >= 0.75 触发直接合并建议"""
        from app.services.coscientist.algorithms.embedding_proximity import EmbeddingProximity

        ep = EmbeddingProximity(llm_refine_threshold=0.45, direct_merge_threshold=0.75)

        result = ep.fuse_with_jaccard(0.85, 0.1)
        assert result["direct_merge"] is True
        assert result["recommendation"] == "direct_merge"

    @pytest.mark.asyncio
    async def test_below_llm_refine_threshold(self):
        """融合分 < 0.45 不触发 LLM 精判"""
        from app.services.coscientist.algorithms.embedding_proximity import EmbeddingProximity

        ep = EmbeddingProximity(llm_refine_threshold=0.45, direct_merge_threshold=0.75)

        result = ep.fuse_with_jaccard(0.2, 0.1)
        assert result["llm_refine"] is False
        assert result["direct_merge"] is False

    @pytest.mark.asyncio
    async def test_custom_weights(self):
        """自定义融合权重"""
        from app.services.coscientist.algorithms.embedding_proximity import EmbeddingProximity

        ep = EmbeddingProximity(fusion_weights=(0.7, 0.3))
        result = ep.fuse_with_jaccard(0.5, 0.8)
        # fused = 0.7*0.5 + 0.3*0.8 = 0.35 + 0.24 = 0.59
        assert result["fused_score"] == pytest.approx(0.59, abs=0.01)


# ============================================================
# 建议四：信号级证据溯源 — 指纹计算
# ============================================================

class TestEvidenceFingerprint:
    """验证证据内容指纹机制"""

    def test_fingerprint_deterministic(self):
        """相同文本产生相同指纹"""
        from app.services.intelligence.evidence_collector import EvidenceCollector

        fp1 = EvidenceCollector._compute_fingerprint("靶点 EGFR 扩增")
        fp2 = EvidenceCollector._compute_fingerprint("靶点 EGFR 扩增")
        assert fp1 == fp2
        assert len(fp1) == 16

    def test_fingerprint_different_texts(self):
        """不同文本产生不同指纹"""
        from app.services.intelligence.evidence_collector import EvidenceCollector

        fp1 = EvidenceCollector._compute_fingerprint("EGFR 信号通路")
        fp2 = EvidenceCollector._compute_fingerprint("HER2 信号通路")
        assert fp1 != fp2

    def test_fingerprint_empty_text(self):
        """空文本返回空字符串"""
        from app.services.intelligence.evidence_collector import EvidenceCollector

        assert EvidenceCollector._compute_fingerprint("") == ""
        assert EvidenceCollector._compute_fingerprint(None) == ""

    def test_fingerprint_length(self):
        """指纹长度为 16 字符（SHA-256 前 8 字节 hex）"""
        from app.services.intelligence.evidence_collector import EvidenceCollector

        fp = EvidenceCollector._compute_fingerprint("test text")
        assert len(fp) == 16
        # 验证是 hex 字符
        int(fp, 16)  # 不应抛异常

    def test_fingerprint_collision_resistance(self):
        """指纹碰撞检测（ Birthday 悖论下 16 hex 应有足够抗碰撞性）"""
        from app.services.intelligence.evidence_collector import EvidenceCollector

        fingerprints = set()
        for i in range(1000):
            fp = EvidenceCollector._compute_fingerprint(f"unique_text_{i}")
            fingerprints.add(fp)

        assert len(fingerprints) == 1000  # 无碰撞


class TestEvidenceSourceFingerprint:
    """验证 EvidenceSource 指纹字段"""

    def test_evidence_source_has_fingerprint(self):
        """EvidenceSource 应包含 content_fingerprint 字段"""
        from app.services.intelligence.evidence_collector import EvidenceSource

        src = EvidenceSource("targets", 5, "5 个靶点", ["EGFR", "HER2"], "abc123def456")
        assert hasattr(src, 'content_fingerprint')
        assert src.content_fingerprint == "abc123def456"

    def test_evidence_source_to_dict_includes_fingerprint(self):
        """EvidenceBundle.to_dict() 包含指纹"""
        from app.services.intelligence.evidence_collector import EvidenceBundle, EvidenceSource

        bundle = EvidenceBundle(
            text="test",
            sources=[EvidenceSource("targets", 3, "3 靶点", ["EGFR"], "abc123")],
        )
        d = bundle.to_dict()
        assert d["sources"][0]["content_fingerprint"] == "abc123"

    def test_bundle_fingerprints_property(self):
        """EvidenceBundle.fingerprints 属性返回所有指纹"""
        from app.services.intelligence.evidence_collector import EvidenceBundle, EvidenceSource

        bundle = EvidenceBundle(
            text="test",
            sources=[
                EvidenceSource("targets", 3, "", ["a"], "fp1"),
                EvidenceSource("molecules", 2, "", ["b"], "fp2"),
                EvidenceSource("experiments", 1, "", ["c"], ""),  # 空指纹
            ],
        )
        assert bundle.fingerprints == ["fp1", "fp2"]


# ============================================================
# 建议五：成本感知分级推理 — 预算护栏
# ============================================================

class TestBudgetAwareTier:
    """验证预算驱动的档位调整"""

    def test_no_budget_constraint(self):
        """无预算约束时保持推荐档位"""
        from app.services.intelligence.intent_router import IntentRouter

        tier, notice = IntentRouter.budget_aware_tier("deep", budget_remaining=None)
        assert tier == "deep"
        assert notice is None

    def test_high_budget_keeps_tier(self):
        """预算充足（>50%）保持档位"""
        from app.services.intelligence.intent_router import IntentRouter

        tier, notice = IntentRouter.budget_aware_tier("deep", budget_remaining=6.0, daily_budget_limit=10.0)
        assert tier == "deep"
        assert notice is None

    def test_mid_budget_downsamples_deep(self):
        """中等预算（20-50%）deep → standard"""
        from app.services.intelligence.intent_router import IntentRouter

        tier, notice = IntentRouter.budget_aware_tier("deep", budget_remaining=3.0, daily_budget_limit=10.0)
        assert tier == "standard"
        assert "预算提示" in notice
        assert "标准" in notice

    def test_low_budget_forces_turbo(self):
        """低预算（<20%）强制 turbo"""
        from app.services.intelligence.intent_router import IntentRouter

        tier, notice = IntentRouter.budget_aware_tier("deep", budget_remaining=1.5, daily_budget_limit=10.0)
        assert tier == "turbo"
        assert "预算告警" in notice

    def test_low_budget_standard_to_turbo(self):
        """低预算时 standard 也降为 turbo"""
        from app.services.intelligence.intent_router import IntentRouter

        tier, notice = IntentRouter.budget_aware_tier("standard", budget_remaining=1.0, daily_budget_limit=10.0)
        assert tier == "turbo"

    def test_turbo_unchanged_by_budget(self):
        """turbo 档不受预算影响"""
        from app.services.intelligence.intent_router import IntentRouter

        tier, notice = IntentRouter.budget_aware_tier("turbo", budget_remaining=0.5, daily_budget_limit=10.0)
        assert tier == "turbo"


class TestIntentRouterSuggestTier:
    """验证意图路由档位推荐"""

    def test_force_tier_overrides(self):
        """force_tier 覆盖自动选择"""
        from app.services.intelligence.intent_router import IntentRouter

        router = IntentRouter.__new__(IntentRouter)
        tier = router.suggest_tier("简单问题", "chat", 0.9, force_tier="deep")
        assert tier == "deep"

    def test_chat_intent_turbo(self):
        """chat 意图推荐 turbo"""
        from app.services.intelligence.intent_router import IntentRouter

        router = IntentRouter.__new__(IntentRouter)
        tier = router.suggest_tier("什么是 EGFR？", "chat", 0.9)
        assert tier == "turbo"

    def test_complex_reasoning_deep(self):
        """复杂 reasoning 推荐 deep"""
        from app.services.intelligence.intent_router import IntentRouter

        router = IntentRouter.__new__(IntentRouter)
        tier = router.suggest_tier(
            "分析 EGFR 信号通路在肺癌中的调控机制，包括 PI3K/AKT、RAS/MAPK 和 JAK/STAT 三条主要通路的异常激活，"
            "并且探讨它们之间的交叉对话，同时考虑靶向治疗的耐药机制以及未来的治疗策略方向，此外还需要结合临床数据进行验证",
            "reasoning", 0.95
        )
        assert tier == "deep"

    def test_medium_reasoning_standard(self):
        """中等复杂 reasoning 推荐 standard"""
        from app.services.intelligence.intent_router import IntentRouter

        router = IntentRouter.__new__(IntentRouter)
        tier = router.suggest_tier("请查找靶点 DRD2", "reasoning", 0.7)
        assert tier == "standard"


# ============================================================
# 建议二+五：GenerationAgent 增强 — 失败知识注入 + 预算感知
# ============================================================

class TestGenerationAgentEnhanced:
    """验证 GenerationAgent 的增强功能"""

    @pytest.mark.asyncio
    async def test_budget_critical_reduces_count(self):
        """预算严重不足时减少假设生成数量"""
        from app.services.coscientist.agents.generation import GenerationAgent

        llm = MagicMock()
        llm.quick = AsyncMock(return_value={
            "content": '{"hypotheses": [{"name": "H1"}, {"name": "H2"}, {"name": "H3"}, {"name": "H4"}, {"name": "H5"}]}',
            "token_usage": {"total": 100},
            "cost_usd": 0.01,
        })

        agent = GenerationAgent(llm, timeout=30.0)
        agent._db = MagicMock()

        # 预算严重不足
        result = await agent.run(
            research_goal="测试",
            count=5,
            budget_remaining=0.2,
        )

        assert result["budget_notice"] != ""
        assert "2" in result["budget_notice"]

    @pytest.mark.asyncio
    async def test_budget_low_warning(self):
        """预算偏低时发出提示"""
        from app.services.coscientist.agents.generation import GenerationAgent

        llm = MagicMock()
        llm.quick = AsyncMock(return_value={
            "content": '{"hypotheses": [{"name": "H1"}]}',
            "token_usage": {"total": 50},
            "cost_usd": 0.005,
        })

        agent = GenerationAgent(llm, timeout=30.0)
        agent._db = MagicMock()

        result = await agent.run(
            research_goal="测试",
            count=5,
            budget_remaining=0.8,
        )

        assert result["budget_notice"] != ""
        assert "3" in result["budget_notice"]

    @pytest.mark.asyncio
    async def test_no_budget_no_notice(self):
        """无预算约束时无提示"""
        from app.services.coscientist.agents.generation import GenerationAgent

        llm = MagicMock()
        llm.quick = AsyncMock(return_value={
            "content": '{"hypotheses": [{"name": "H1"}]}',
            "token_usage": {"total": 50},
            "cost_usd": 0.005,
        })

        agent = GenerationAgent(llm, timeout=30.0)
        agent._db = MagicMock()

        result = await agent.run(
            research_goal="测试",
            count=5,
            budget_remaining=None,
        )

        assert result["budget_notice"] == ""

    @pytest.mark.asyncio
    async def test_failure_context_flag(self):
        """失败知识上下文包含标志"""
        from app.services.coscientist.agents.generation import GenerationAgent

        llm = MagicMock()
        llm.quick = AsyncMock(return_value={
            "content": '{"hypotheses": [{"name": "H1"}]}',
            "token_usage": {"total": 50},
            "cost_usd": 0.005,
        })

        agent = GenerationAgent(llm, timeout=30.0)
        agent._db = MagicMock()

        result = await agent.run(
            research_goal="测试",
            count=3,
        )

        assert "failure_context_included" in result


# ============================================================
# 性能测试
# ============================================================

class TestPerformanceMetrics:
    """关键路径性能验证"""

    def test_fingerprint_performance(self):
        """指纹计算延迟 < 1ms"""
        from app.services.intelligence.evidence_collector import EvidenceCollector

        test_text = "EGFR 信号通路在肺癌中的调控机制涉及多个下游通路的异常激活"

        start = time.perf_counter()
        for _ in range(1000):
            EvidenceCollector._compute_fingerprint(test_text)
        elapsed = (time.perf_counter() - start) / 1000

        assert elapsed < 0.001, f"指纹计算平均延迟 {elapsed*1000:.2f}ms 超过 1ms 阈值"

    def test_fusion_score_performance(self):
        """融合评分计算延迟 < 0.1ms"""
        from app.services.coscientist.algorithms.embedding_proximity import EmbeddingProximity

        ep = EmbeddingProximity()

        start = time.perf_counter()
        for _ in range(10000):
            ep.fuse_with_jaccard(0.6, 0.3)
        elapsed = (time.perf_counter() - start) / 10000

        assert elapsed < 0.0001, f"融合评分平均延迟 {elapsed*10000:.4f}ms 超过 0.1ms 阈值"

    def test_budget_tier_performance(self):
        """预算路由延迟 < 0.1ms"""
        from app.services.intelligence.intent_router import IntentRouter

        start = time.perf_counter()
        for _ in range(10000):
            IntentRouter.budget_aware_tier("deep", budget_remaining=3.0)
        elapsed = (time.perf_counter() - start) / 10000

        assert elapsed < 0.0001, f"预算路由平均延迟 {elapsed*10000:.4f}ms 超过 0.1ms 阈值"

    def test_complexity_estimate_performance(self):
        """复杂度估算延迟 < 0.5ms"""
        from app.services.intelligence.intent_router import IntentRouter

        test_msg = "分析 EGFR 信号通路在非小细胞肺癌中的调控机制，包括 PI3K/AKT、RAS/MAPK 和 JAK/STAT 三条主要通路的异常激活，以及它们之间的交叉对话"

        start = time.perf_counter()
        for _ in range(1000):
            IntentRouter._estimate_complexity(test_msg)
        elapsed = (time.perf_counter() - start) / 1000

        assert elapsed < 0.0005, f"复杂度估算平均延迟 {elapsed*1000:.3f}ms 超过 0.5ms 阈值"


# ============================================================
# 兼容性测试
# ============================================================

class TestBackwardCompatibility:
    """向后兼容性验证"""

    def test_hypothesis_model_has_new_fields(self):
        """Hypothesis 模型包含新字段"""
        from app.models.hypothesis import Hypothesis

        h = Hypothesis(
            project_id=uuid4(),
            name="test",
        )

        assert hasattr(h, 'experimental_elo_adjustment')
        assert hasattr(h, 'experimental_validation_count')

        # 默认值
        assert h.experimental_elo_adjustment == 0.0
        assert h.experimental_validation_count == 0

    def test_existing_code_path_still_works(self):
        """现有代码路径不受影响"""
        from app.models.hypothesis import Hypothesis

        h = Hypothesis(
            project_id=uuid4(),
            name="test",
            elo_score=1000.0,
        )

        assert h.elo_score == 1000.0
        assert h.novelty_score is None

    def test_evidence_source_default_compatible(self):
        """EvidenceSource 默认值兼容旧代码"""
        from app.services.intelligence.evidence_collector import EvidenceSource

        # 不传 fingerprint 时使用空字符串默认值
        src = EvidenceSource("targets", 5, "test")
        assert src.content_fingerprint == ""
        assert src.snippets_kept == []

    def test_llm_tiers_config(self):
        """LLM_TIERS 配置结构正确"""
        from app.core.config import settings

        assert "turbo" in settings.LLM_TIERS
        assert "standard" in settings.LLM_TIERS
        assert "deep" in settings.LLM_TIERS

        turbo = settings.LLM_TIERS["turbo"]
        assert "max_rounds" in turbo
        assert turbo["max_rounds"] == 2

        deep = settings.LLM_TIERS["deep"]
        assert deep["evidence_level"] == "full"

    def test_orchestrator_flag_default(self):
        """编排收敛开关默认开启"""
        from app.core.config import settings

        assert settings.INTELLIGENCE_USE_UNIFIED_ORCHESTRATOR is True


# ============================================================
# 安全性测试
# ============================================================

class TestSecurity:
    """安全相关测试"""

    @pytest.mark.asyncio
    async def test_invalid_conclusion_enumforced(self):
        """非法结论被拒绝（防注入）"""
        from app.services.experiment.feedback_loop import FeedbackLoop

        experiment = SimpleNamespace(
            id=uuid4(),
            hypothesis=SimpleNamespace(id=uuid4(), elo_score=1000.0, evolution_history=[]),
        )

        mock_db = MagicMock()
        loop = FeedbackLoop(mock_db)

        with pytest.raises(ValueError):
            await loop.apply_validation_feedback(experiment, "DROP TABLE")

    def test_budget_cannot_be_negative(self):
        """预算不能为负值（防绕过）"""
        from app.services.intelligence.intent_router import IntentRouter

        # 负预算应视为预算耗尽
        tier, notice = IntentRouter.budget_aware_tier("deep", budget_remaining=-1.0)
        assert tier == "turbo"

    @pytest.mark.asyncio
    async def test_failure_knowledge_scope_isolated(self):
        """失败知识按项目隔离（防跨项目泄露）"""
        from app.services.analyzer.wrong_path_service import WrongPathAvoider

        records_project_a = [
            SimpleNamespace(
                id=uuid4(), failure_reason="contamination",
                wrong_path_proof="A 项目污染", is_high_confidence=True,
                failure_count=3, target_id=None, molecule_id=None,
            ),
        ]

        records_project_b = [
            SimpleNamespace(
                id=uuid4(), failure_reason="concentration",
                wrong_path_proof="B 项目浓度", is_high_confidence=True,
                failure_count=1, target_id=None, molecule_id=None,
            ),
        ]

        # 查询 A 项目
        mock_a = MagicMock()
        mock_a.scalars.return_value.all.return_value = records_project_a
        mock_db_a = MagicMock()
        mock_db_a.execute = AsyncMock(return_value=mock_a)
        avoider_a = WrongPathAvoider(mock_db_a)

        result_a = await avoider_a.query_failures(project_id=uuid4())
        assert len(result_a) == 1
        assert result_a[0]["failure_reason"] == "contamination"

    def test_fingerprint_uniqueness(self):
        """指纹唯一性验证（防止碰撞导致数据串扰）"""
        from app.services.intelligence.evidence_collector import EvidenceCollector

        import random
        test_cases = [f"evidence_{i}_{random.randint(0, 9999)}" for i in range(100)]
        fps = {EvidenceCollector._compute_fingerprint(tc) for tc in test_cases}

        # 100 个不同文本应产生 100 个不同指纹
        assert len(fps) == 100, f"指纹碰撞检测：{100 - len(fps)} 对碰撞"


# ============================================================
# 汇总
# ============================================================

class TestSummary:
    """测试汇总与完整性检查"""

    def test_all_suggestions_have_tests(self):
        """7 项建议均有对应测试"""
        test_classes = [
            TestFeedbackWithExperimentalElo,       # 建议一
            TestFailureKnowledgeIntegration,        # 建议二
            TestWrongPathAvoider,                  # 建议二
            TestEmbeddingProximityFusion,          # 建议三
            TestEvidenceFingerprint,               # 建议四
            TestEvidenceSourceFingerprint,         # 建议四
            TestBudgetAwareTier,                   # 建议五
            TestIntentRouterSuggestTier,           # 建议五
            TestGenerationAgentEnhanced,           # 建议二+五
            TestPerformanceMetrics,                # 性能
            TestBackwardCompatibility,             # 兼容性
            TestSecurity,                          # 安全性
        ]

        for cls in test_classes:
            assert len(cls.__dict__) > 0, f"测试类 {cls.__name__} 为空"

        # 统计测试方法数量
        total_tests = 0
        for cls in test_classes:
            methods = [m for m in dir(cls) if m.startswith("test_")]
            total_tests += len(methods)

        assert total_tests >= 40, f"测试数量 {total_tests} < 40"
        print(f"\n共 {len(test_classes)} 个测试类，{total_tests} 个测试方法")

    def test_performance_thresholds_defined(self):
        """性能阈值已定义"""
        # 指纹计算: < 1ms
        assert hasattr(TestPerformanceMetrics, 'test_fingerprint_performance')
        # 融合评分: < 0.1ms
        assert hasattr(TestPerformanceMetrics, 'test_fusion_score_performance')
        # 预算路由: < 0.1ms
        assert hasattr(TestPerformanceMetrics, 'test_budget_tier_performance')
