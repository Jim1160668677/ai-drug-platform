"""EmbeddingProximity 单元测试 — 语义嵌入邻近度计算与融合"""
import asyncio
import math
import pytest

from app.services.coscientist.algorithms.embedding_proximity import EmbeddingProximity


class MockLLMWithEmbed:
    """支持 embed 方法的 Mock LLM 客户端"""

    async def embed(self, text: str):
        await asyncio.sleep(0)
        import hashlib
        h = hashlib.sha256(text.encode()).digest()
        vec = []
        for i in range(0, len(h) * 30, 4):
            chunk = h[i % len(h):i % len(h) + 4].ljust(4, b'\x00')
            vec.append(float(int.from_bytes(chunk[:4], 'little', signed=True)))
        return vec[:1536]


class MockLLMWithoutEmbed:
    """不支持 embed 方法的 Mock LLM 客户端（Mock 模式降级）"""

    async def chat(self, messages, **kwargs):
        return {"content": "ok", "usage": {}, "model": "mock"}


class FailingEmbedClient:
    """embed 调用失败的 Mock LLM"""

    async def embed(self, text: str):
        raise RuntimeError("Embedding service unavailable")


def _hyp(hid="1", name="测试", desc="描述", mech="机制"):
    return {"id": hid, "name": name, "description": desc, "mechanism": mech}


class TestEmbeddingProximityInit:
    def test_init_with_llm(self):
        llm = MockLLMWithEmbed()
        ep = EmbeddingProximity(llm_client=llm)
        assert ep.embed_available is True

    def test_init_without_llm(self):
        ep = EmbeddingProximity(llm_client=None)
        assert ep.embed_available is False

    def test_init_without_embed_method(self):
        llm = MockLLMWithoutEmbed()
        ep = EmbeddingProximity(llm_client=llm)
        assert ep.embed_available is False

    def test_custom_weights(self):
        ep = EmbeddingProximity(fusion_weights=(0.7, 0.3))
        assert ep.fusion_weights == (0.7, 0.3)

    def test_custom_thresholds(self):
        ep = EmbeddingProximity(
            llm_refine_threshold=0.55,
            direct_merge_threshold=0.85,
        )
        assert ep.llm_refine_threshold == 0.55
        assert ep.direct_merge_threshold == 0.85


class TestCosineSimilarity:
    def test_identical_vectors(self):
        vec = [1.0, 2.0, 3.0]
        score = EmbeddingProximity._cosine_similarity(vec, vec)
        assert score == pytest.approx(1.0, abs=1e-6)

    def test_orthogonal_vectors(self):
        vec_a = [1.0, 0.0]
        vec_b = [0.0, 1.0]
        score = EmbeddingProximity._cosine_similarity(vec_a, vec_b)
        assert score == pytest.approx(0.0, abs=1e-6)

    def test_empty_vectors(self):
        score = EmbeddingProximity._cosine_similarity([], [])
        assert score == 0.0

    def test_zero_norm_vector(self):
        score = EmbeddingProximity._cosine_similarity([0.0, 0.0], [1.0, 2.0])
        assert score == 0.0

    def test_different_length_vectors(self):
        vec_a = [1.0, 0.0, 0.0]
        vec_b = [0.5, 0.5]
        score = EmbeddingProximity._cosine_similarity(vec_a, vec_b)
        assert 0.0 <= score <= 1.0

    def test_similar_but_not_identical(self):
        vec_a = [1.0, 0.0, 0.0]
        vec_b = [0.9, 0.1, 0.0]
        score = EmbeddingProximity._cosine_similarity(vec_a, vec_b)
        assert score > 0.9


class TestTFIDFVectorization:
    def test_tfidf_two_docs(self):
        ep = EmbeddingProximity(llm_client=None)
        texts = ["EGFR inhibitor therapy", "EGFR inhibitor treatment"]
        vectors = ep._tfidf_vectors(texts)
        assert len(vectors) == 2
        assert all(isinstance(v, list) for v in vectors)
        assert all(len(v) > 0 for v in vectors)

        score = EmbeddingProximity._cosine_similarity(vectors[0], vectors[1])
        assert score > 0.3

    def test_tfidf_empty_texts(self):
        ep = EmbeddingProximity(llm_client=None)
        vectors = ep._tfidf_vectors(["", ""])
        assert len(vectors) == 2
        assert all(v == [0.0] for v in vectors)

    def test_tfidf_chinese_text(self):
        ep = EmbeddingProximity(llm_client=None)
        texts = ["EGFR靶向治疗", "EGFR信号通路抑制"]
        vectors = ep._tfidf_vectors(texts)
        assert len(vectors) == 2
        assert all(len(v) > 0 for v in vectors)

    def test_tfidf_identical_texts(self):
        ep = EmbeddingProximity(llm_client=None)
        text = "EGFR inhibitor for NSCLC treatment"
        vectors = ep._tfidf_vectors([text, text])
        score = EmbeddingProximity._cosine_similarity(vectors[0], vectors[1])
        assert score == pytest.approx(1.0, abs=1e-6)


class TestComputeSimilarities:
    @pytest.mark.asyncio
    async def test_compute_with_llm_embed(self):
        llm = MockLLMWithEmbed()
        ep = EmbeddingProximity(llm_client=llm)
        hyps = [_hyp("1", "EGFR抑制剂", "抑制EGFR通路", "阻断EGFR信号"),
                _hyp("2", "EGFR靶向", "靶向EGFR治疗", "抑制EGFR")]
        result = await ep.compute_similarities(hyps)
        assert result["method"] == "llm_embed"
        assert len(result["matrix"]) == 1
        assert len(result["vectors"]) == 2
        assert result["embed_available"] is True

    @pytest.mark.asyncio
    async def test_compute_with_tfidf_fallback(self):
        llm = MockLLMWithoutEmbed()
        ep = EmbeddingProximity(llm_client=llm)
        hyps = [_hyp("1", "EGFR抑制剂", "描述1", "机制1"),
                _hyp("2", "不同靶点", "描述2", "机制2")]
        result = await ep.compute_similarities(hyps)
        assert result["method"] == "tfidf"
        assert len(result["matrix"]) == 1
        assert result["embed_available"] is False

    @pytest.mark.asyncio
    async def test_compute_single_hypothesis(self):
        ep = EmbeddingProximity(llm_client=None)
        result = await ep.compute_similarities([_hyp()])
        assert result["matrix"] == {}
        assert result["vectors"] == {}
        assert result["method"] == "none"

    @pytest.mark.asyncio
    async def test_compute_failing_embed_fallback(self):
        llm = FailingEmbedClient()
        ep = EmbeddingProximity(llm_client=llm)
        hyps = [_hyp("1", "EGFR", "desc1", "mech1"),
                _hyp("2", "HER2", "desc2", "mech2")]
        result = await ep.compute_similarities(hyps)
        assert result["method"] == "tfidf"

    @pytest.mark.asyncio
    async def test_compute_similar_texts_high_score(self):
        llm = MockLLMWithEmbed()
        ep = EmbeddingProximity(llm_client=llm)
        hyps = [
            _hyp("1", "EGFR Inhibitor", "Small molecule inhibiting EGFR tyrosine kinase", "Blocks EGFR signaling cascade"),
            _hyp("2", "EGFR Blocker", "Inhibits EGFR kinase activity", "Blocks EGFR pathway transduction"),
        ]
        result = await ep.compute_similarities(hyps)
        for pair_key, data in result["matrix"].items():
            assert data["embedding_score"] >= 0.0

    @pytest.mark.asyncio
    async def test_compute_three_hypotheses(self):
        ep = EmbeddingProximity(llm_client=None)
        hyps = [_hyp("1", "A", "desc A", "mech A"),
                _hyp("2", "B", "desc B", "mech B"),
                _hyp("3", "C", "desc C", "mech C")]
        result = await ep.compute_similarities(hyps)
        assert len(result["matrix"]) == 3


class TestFuseWithJaccard:
    def test_fuse_normal_case(self):
        ep = EmbeddingProximity()
        result = ep.fuse_with_jaccard(0.5, 0.3)
        assert result["fused_score"] == pytest.approx(0.42, abs=1e-4)
        assert result["llm_refine"] is False
        assert result["direct_merge"] is False
        assert result["recommendation"] == "keep_separate"

    def test_fuse_triggers_llm_refine(self):
        ep = EmbeddingProximity(llm_refine_threshold=0.45)
        result = ep.fuse_with_jaccard(0.6, 0.5)
        assert result["fused_score"] == pytest.approx(0.56, abs=1e-4)
        assert result["llm_refine"] is True
        assert result["direct_merge"] is False
        assert result["recommendation"] == "llm_refine"

    def test_fuse_direct_merge(self):
        ep = EmbeddingProximity(direct_merge_threshold=0.75)
        result = ep.fuse_with_jaccard(0.85, 0.1)
        assert result["direct_merge"] is True
        assert result["recommendation"] == "direct_merge"
        assert result["fused_score"] == pytest.approx(0.55, abs=1e-4)

    def test_fuse_custom_weights(self):
        ep = EmbeddingProximity(fusion_weights=(0.7, 0.3))
        result = ep.fuse_with_jaccard(0.5, 0.4)
        expected = 0.7 * 0.5 + 0.3 * 0.4
        assert result["fused_score"] == pytest.approx(expected, abs=1e-4)

    def test_fuse_with_runtime_weights(self):
        ep = EmbeddingProximity(fusion_weights=(0.6, 0.4))
        result = ep.fuse_with_jaccard(0.5, 0.5, weights=(0.8, 0.2))
        expected = 0.8 * 0.5 + 0.2 * 0.5
        assert result["fused_score"] == pytest.approx(expected, abs=1e-4)

    def test_fuse_zero_scores(self):
        ep = EmbeddingProximity()
        result = ep.fuse_with_jaccard(0.0, 0.0)
        assert result["fused_score"] == 0.0
        assert result["recommendation"] == "keep_separate"

    def test_fuse_max_clamp(self):
        ep = EmbeddingProximity()
        result = ep.fuse_with_jaccard(1.5, 1.5)
        assert result["fused_score"] == 1.0

    def test_fuse_min_clamp(self):
        ep = EmbeddingProximity()
        result = ep.fuse_with_jaccard(-0.1, -0.1)
        assert result["fused_score"] == 0.0


class TestComputeAndFuse:
    @pytest.mark.asyncio
    async def test_compute_and_fuse(self):
        ep = EmbeddingProximity(llm_client=None)
        hyps = [
            _hyp("1", "EGFR inhibitor", "Treats NSCLC by inhibiting EGFR", "Blocks EGFR signaling"),
            _hyp("2", "EGFR antibody", "Anti-EGFR antibody therapy", "Binds EGFR receptor"),
            _hyp("3", "Immunotherapy", "PD-1 checkpoint inhibitor", "Activates T cells"),
        ]
        jaccard_scores = {
            ("1", "2"): 0.6,
            ("1", "3"): 0.1,
            ("2", "3"): 0.15,
        }
        result = await ep.compute_and_fuse(hyps, jaccard_scores)
        assert len(result["matrix"]) == 3
        assert "stats" in result
        total = result["stats"]["direct_merge"] + result["stats"]["llm_refine"] + result["stats"]["keep_separate"]
        assert total == 3

    @pytest.mark.asyncio
    async def test_compute_and_fuse_empty(self):
        ep = EmbeddingProximity(llm_client=None)
        result = await ep.compute_and_fuse([], {})
        assert result["matrix"] == {}
        assert result["stats"]["direct_merge"] == 0
        assert result["stats"]["llm_refine"] == 0
        assert result["stats"]["keep_separate"] == 0


class TestHypothesisToText:
    def test_full_hypothesis(self):
        h = {"name": "Test", "description": "Desc", "mechanism": "Mech"}
        text = EmbeddingProximity._hypothesis_to_text(h)
        assert "Test" in text
        assert "Desc" in text
        assert "Mech" in text

    def test_empty_hypothesis(self):
        text = EmbeddingProximity._hypothesis_to_text({})
        assert text == ""

    def test_partial_hypothesis(self):
        h = {"name": "Test"}
        text = EmbeddingProximity._hypothesis_to_text(h)
        assert text == "Test"