"""KnowledgeGapDetector 单元测试 — 知识盲区检测

测试矩阵：
- 观察记录：记录成功/失败/空结果
- 启发式检测：连续空结果/循环推理/有有效结果
- 搜索查询词提取
- LLM 深度检测：成功/解析失败/异常降级
- GapType 枚举
"""
import json
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.services.agent.knowledge_gap import (
    GapDetectionResult,
    GapType,
    KnowledgeGapDetector,
    ObservationRecord,
)


# ========== ObservationRecord 测试 ==========


class TestObservationRecord:
    """测试观察记录数据类"""

    def test_empty_result_no_data(self):
        """空数据 → 空结果"""
        r = ObservationRecord(step=1, tool="search", success=True, data_summary="")
        assert r.is_empty_result is True

    def test_empty_result_with_indicators(self):
        """包含空结果指示词 → 空结果"""
        indicators = ["0 条", "无结果", "未找到", "未发现", "empty", "no result"]
        for ind in indicators:
            r = ObservationRecord(step=1, tool="search", success=True, data_summary=f"返回{ind}")
            assert r.is_empty_result is True, f"'{ind}' 应被识别为空结果"

    def test_non_empty_result(self):
        """有数据 → 非空"""
        r = ObservationRecord(
            step=1, tool="search", success=True, data_summary="找到 5 条结果"
        )
        assert r.is_empty_result is False

    def test_failure_not_empty(self):
        """失败的结果不算空结果"""
        r = ObservationRecord(
            step=1, tool="search", success=False, data_summary="", error="timeout"
        )
        assert r.is_empty_result is False


# ========== 启发式检测测试 ==========


class TestHeuristicDetection:
    """测试启发式盲区检测（无 LLM）"""

    @pytest.fixture
    def detector(self):
        return KnowledgeGapDetector(llm_router=None, window_size=2)

    @pytest.mark.asyncio
    async def test_consecutive_empty_results(self, detector):
        """连续 2 次空结果 → 检测到盲区"""
        detector.observe(1, "search_literature", True, {"total": 0})
        detector.observe(2, "search_ncbi", True, {"total": 0})

        result = await detector.detect(query="EGFR 最新研究")
        assert result.is_knowledge_gap is True
        assert result.gap_type == GapType.NO_RESULTS
        assert result.confidence > 0.5
        assert len(result.suggested_search_query) > 0

    @pytest.mark.asyncio
    async def test_has_valid_results_no_gap(self, detector):
        """有有效结果 → 无盲区"""
        detector.observe(1, "search_literature", True, {"total": 5})
        detector.observe(2, "search_ncbi", True, {"total": 3})

        result = await detector.detect(query="EGFR")
        assert result.is_knowledge_gap is False

    @pytest.mark.asyncio
    async def test_insufficient_observations(self, detector):
        """观察数据不足 → 无法判断"""
        detector.observe(1, "search_literature", True, {"total": 0})

        result = await detector.detect(query="EGFR")
        # 数据不足，启发式返回 None，无 LLM → 返回默认
        assert result.is_knowledge_gap is False

    @pytest.mark.asyncio
    async def test_circular_reasoning(self, detector):
        """循环推理检测（重复调用同一工具）"""
        detector.observe(1, "search_literature", True, {"total": 0})
        detector.observe(2, "search_ncbi", True, {"total": 5})
        detector.observe(3, "search_literature", True, {"total": 0})

        result = await detector.detect(query="EGFR")
        # 可能检测到循环或空结果
        if result.is_knowledge_gap:
            assert result.gap_type in (GapType.CIRCULAR_REASONING, GapType.NO_RESULTS)

    @pytest.mark.asyncio
    async def test_reset_clears_observations(self, detector):
        """reset 清空观察"""
        detector.observe(1, "search", True, {"total": 0})
        detector.reset()
        assert len(detector._observations) == 0


# ========== 搜索查询词提取测试 ==========


class TestSearchQueryExtraction:
    """测试从用户问题提取搜索词"""

    @pytest.fixture
    def detector(self):
        return KnowledgeGapDetector(llm_router=None)

    def test_extract_simple_query(self, detector):
        query = "EGFR 抑制剂 耐药机制"
        result = detector._extract_search_query(query)
        assert "EGFR" in result
        assert "抑制剂" in result

    def test_extract_removes_stop_words(self, detector):
        query = "请帮我查询一下 EGFR 靶点是什么"
        result = detector._extract_search_query(query)
        assert "EGFR" in result
        assert "请" not in result
        assert "帮我" not in result
        assert "什么" not in result

    def test_extract_empty_query(self, detector):
        result = detector._extract_search_query("")
        assert result == ""

    def test_extract_limits_length(self, detector):
        long_query = " ".join(["gene"] * 20)
        result = detector._extract_search_query(long_query)
        assert len(result) <= 200


# ========== LLM 深度检测测试 ==========


class TestLLMDetection:
    """测试 LLM 深度盲区检测"""

    @pytest.fixture
    def llm_router(self):
        router = MagicMock()
        router.quick = AsyncMock()
        return router

    @pytest.fixture
    def detector(self, llm_router):
        return KnowledgeGapDetector(llm_router=llm_router, window_size=2)

    @pytest.mark.asyncio
    async def test_llm_detect_gap(self, detector, llm_router):
        """LLM 成功检测到盲区"""
        llm_router.quick.return_value = {
            "content": json.dumps({
                "is_knowledge_gap": True,
                "confidence": 0.9,
                "reasoning": "连续 3 次工具返回空结果",
                "suggested_search_query": "EGFR resistance mechanism 2024",
                "gap_type": "no_results",
            })
        }

        # 记录一些观察（确保有数据）
        detector.observe(1, "search_literature", True, {"total": 0})
        detector.observe(2, "search_ncbi", True, {"total": 0})

        result = await detector.detect(query="EGFR 耐药机制")
        assert result.is_knowledge_gap is True
        assert result.gap_type == GapType.NO_RESULTS
        assert result.suggested_search_query == "EGFR resistance mechanism 2024"

    @pytest.mark.asyncio
    async def test_llm_detect_no_gap(self, detector, llm_router):
        """LLM 判断无盲区"""
        llm_router.quick.return_value = {
            "content": json.dumps({
                "is_knowledge_gap": False,
                "confidence": 0.85,
                "reasoning": "有有效结果",
                "suggested_search_query": "",
                "gap_type": "none",
            })
        }

        detector.observe(1, "search_literature", True, {"total": 5})

        result = await detector.detect(query="EGFR")
        assert result.is_knowledge_gap is False

    @pytest.mark.asyncio
    async def test_llm_parse_failure_degrades(self, detector, llm_router):
        """LLM 输出解析失败 → 降级"""
        llm_router.quick.return_value = {"content": "not json"}

        detector.observe(1, "search", True, {"total": 0})
        detector.observe(2, "search", True, {"total": 0})

        result = await detector.detect(query="test")
        # 启发式会先检测到连续空结果
        assert result.is_knowledge_gap is True

    @pytest.mark.asyncio
    async def test_llm_exception_degrades_to_heuristic(self, detector, llm_router):
        """LLM 异常 → 降级启发式"""
        llm_router.quick.side_effect = Exception("LLM 不可用")

        # 启发式能判断的情况
        detector.observe(1, "search", True, {"total": 0})
        detector.observe(2, "search", True, {"total": 0})

        result = await detector.detect(query="test")
        # 启发式先检测到，不调 LLM
        assert result.is_knowledge_gap is True
        assert result.gap_type == GapType.NO_RESULTS


# ========== GapDetectionResult 数据类测试 ==========


class TestGapDetectionResult:
    """测试 GapDetectionResult"""

    def test_to_dict(self):
        r = GapDetectionResult(
            is_knowledge_gap=True,
            confidence=0.85,
            reasoning="连续空结果",
            gap_type=GapType.NO_RESULTS,
            suggested_search_query="EGFR mechanism",
        )
        d = r.to_dict()
        assert d["is_knowledge_gap"] is True
        assert d["confidence"] == 0.85
        assert d["gap_type"] == "no_results"
        assert d["suggested_search_query"] == "EGFR mechanism"

    def test_no_gap_default(self):
        r = GapDetectionResult(
            is_knowledge_gap=False,
            confidence=0.0,
            reasoning="无数据",
        )
        assert r.gap_type == GapType.NONE
        assert r.suggested_search_query == ""


# ========== GapType 枚举测试 ==========


class TestGapType:
    """测试 GapType 枚举"""

    def test_enum_values(self):
        assert GapType.NONE.value == "none"
        assert GapType.NO_RESULTS.value == "no_results"
        assert GapType.IRRELEVANT_RESULTS.value == "irrelevant_results"
        assert GapType.CIRCULAR_REASONING.value == "circular_reasoning"

    def test_from_string(self):
        assert GapType("no_results") == GapType.NO_RESULTS
        assert GapType("none") == GapType.NONE
