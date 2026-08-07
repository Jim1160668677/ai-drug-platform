"""LLM 响应缓存 & 淘汰假设摘要 测试"""
from app.services.coscientist.response_cache import ResponseCache


class TestResponseCache:
    def test_get_miss_put_get_hit(self):
        cache = ResponseCache(maxsize=2)
        assert cache.get("prompt_A") is None
        cache.put("prompt_A", {"content": "ans_A", "cost": 0.01})
        r = cache.get("prompt_A")
        assert r is not None
        assert r["content"] == "ans_A"

    def test_lru_eviction(self):
        cache = ResponseCache(maxsize=2)
        cache.put("A", {"content": "1"})
        cache.put("B", {"content": "2"})
        assert cache.get("A")["content"] == "1"
        cache.put("C", {"content": "3"})
        assert cache.get("B") is None
        assert cache.get("A") is not None
        assert cache.get("C") is not None

    def test_key_normalization_strips_whitespace(self):
        cache = ResponseCache(maxsize=4)
        cache.put(" X\n\n", {"content": "hi"})
        assert cache.get("  X  ")["content"] == "hi"


class TestHypothesisCompressionHelpers:
    def test_compact_evicted_hypotheses_keeps_names_and_scores(self):
        from app.services.coscientist.supervisor import _compact_evicted_hypotheses
        old = [
            {"name": "Hyp-A", "description": "非常长的描述...省略千万字", "mechanism": "A→B→C→D→E",
             "novelty_score": 8.0, "plausibility_score": 7.0, "elo_score": 1100},
            {"name": "Hyp-B", "description": "另一篇长描述", "mechanism": "B→C",
             "novelty_score": 5.0, "plausibility_score": 5.0, "elo_score": 1000},
        ]
        compact = _compact_evicted_hypotheses(old)
        assert isinstance(compact, str)
        assert "Hyp-A" in compact and "Hyp-B" in compact
        assert "省略千万字" not in compact or len(compact) < 600
        assert "1100" in compact
