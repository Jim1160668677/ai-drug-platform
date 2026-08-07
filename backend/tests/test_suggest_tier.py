"""TierSuggest 端点与 Schema 测试"""
import pytest

from app.schemas.intelligence import TierSuggestRequest, TierSuggestResponse


def test_suggest_tier_schema_turbo():
    req = TierSuggestRequest(message="什么是 EGFR?")
    assert req.message == "什么是 EGFR?"


def test_suggest_tier_schema_complex():
    req = TierSuggestRequest(message="请分析 EGFR 在 NSCLC 中的耐药机制并设计联合用药方案")
    assert len(req.message) > 20


def test_tier_suggest_response_fields():
    resp = TierSuggestResponse(tier="turbo", reason="test", confidence=0.5, tier_config={})
    assert resp.tier == "turbo"
    assert resp.confidence == 0.5
