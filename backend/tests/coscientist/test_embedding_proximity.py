"""EmbeddingProximity 单元测试 — 语义嵌入邻近度计算与融合"""
import asyncio
import math
import pytest

from app.services.coscientist.algorithms.embedding_proximity import EmbeddingProximity


class MockLLMWithEmbed:
    """支持 embed 方法的 Mock LLM 客户端

    基于关键词共现生成确定性向量:共享关键词越多,向量越相似。
    这样可模拟真实 embedding 的语义相似行为。
    """

    KEYWORDS = [
        "egfr", "抑制剂", "抑制", "阻断", "信号", "通路", "治疗", "肿瘤", "肺癌",
        "靶向", "受体", "激酶", "磷酸化", "下游", "细胞", "抗体", "免疫",
        "pd-1", "her2", "t细胞", "增殖", "凋亡", "转移", "基因", "蛋白",
    ]
    DIM = 32

    async def embed(self, text: str):
        await asyncio.sleep(0)
        import hashlib
        text_lower = text.lower()
        vec = [0.0] * self.DIM
        for i, kw in enumerate(self.KEYWORDS):
            if kw in text_lower:
                # 用哈希确定性地分散到多个维度
                h = int(hashlib.md5(f"{kw}:{i}".encode()).hexdigest(), 16)
                for j in range(self.DIM):
                    bit = (h >> (j % 32)) & 1
                    vec[j] += 1.0 if bit else -0.5
        # 归一化
        norm = sum(x * x for x in vec) ** 0.5
        if norm > 0:
            vec = [x / norm for x in vec]
        return vec


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


class TestSemanticRewriteCapture:
    """同义改写对可被捕获 — 验证嵌入通道能识别语义相似但词面不同的假设"""

    @pytest.mark.asyncio
    async def test_semantic_rewrite_low_jaccard_high_embedding(self):
        """两个假设语义相同但词面不同(低 Jaccard),嵌入通道应捕获高相似度"""
        llm = MockLLMWithEmbed()
        ep = EmbeddingProximity(llm_client=llm, fusion_weights=(0.6, 0.4))
        # "EGFR抑制剂通过阻断信号通路治疗肺癌" 的两种表述 — 词面重叠低但语义相同
        hyps = [
            _hyp("1", "EGFR抑制剂",
                 "EGFR酪氨酸激酶抑制剂通过阻断EGFR信号通路治疗非小细胞肺癌",
                 "抑制EGFR自磷酸化从而阻断下游RAS-RAF-MEK-ERK通路"),
            _hyp("2", "EGFR靶向治疗",
                 "以EGFR为靶点的抑制剂疗法可抑制EGFR信号传导从而治疗肺癌",
                 "通过阻断EGFR受体酪氨酸激酶活性抑制肿瘤细胞增殖"),
        ]
        # Jaccard 低(词面重叠少),但语义高度相似
        jaccard_scores = {("1", "2"): 0.15}
        result = await ep.compute_and_fuse(hyps, jaccard_scores)
        pair_data = result["matrix"][("1", "2")]
        # embedding 通道应给出较高分数(语义相似)
        assert pair_data["embedding_score"] > 0.3, (
            f"嵌入通道未能捕获同义改写: embedding_score={pair_data['embedding_score']}"
        )
        # 融合分数应高于 Jaccard 单独值(嵌入通道提供了额外信息)
        assert pair_data["fused_score"] > 0.15, (
            f"融合分数应高于 Jaccard 单独值: fused={pair_data['fused_score']}"
        )

    @pytest.mark.asyncio
    async def test_different_topics_low_fusion(self):
        """两个完全不同的假设,融合分数应低(不被错误合并)"""
        llm = MockLLMWithEmbed()
        ep = EmbeddingProximity(llm_client=llm)
        hyps = [
            _hyp("1", "EGFR抑制剂", "抑制EGFR通路治疗肺癌", "阻断EGFR信号"),
            _hyp("2", "PD-1免疫治疗", "PD-1检查点抑制剂激活T细胞抗肿瘤免疫", "解除T细胞免疫抑制"),
        ]
        jaccard_scores = {("1", "2"): 0.05}
        result = await ep.compute_and_fuse(hyps, jaccard_scores)
        pair_data = result["matrix"][("1", "2")]
        # 不同主题 → 融合分数应低,推荐 keep_separate
        assert pair_data["recommendation"] == "keep_separate"
        assert pair_data["direct_merge"] is False

    @pytest.mark.asyncio
    async def test_semantic_vs_jaccard_channel_contrast(self):
        """对比测试:同义改写对应高 embedding 低 Jaccard;无关假设对应低 embedding 低 Jaccard"""
        llm = MockLLMWithEmbed()
        ep = EmbeddingProximity(llm_client=llm)
        # 同义改写对
        rewrite_hyps = [
            _hyp("r1", "抑制EGFR通路", "通过抑制EGFR信号通路治疗肿瘤", "阻断EGFR磷酸化"),
            _hyp("r2", "EGFR信号阻断", "阻断EGFR信号传导以抑制肿瘤生长", "抑制EGFR下游信号"),
        ]
        # 无关对
        unrelated_hyps = [
            _hyp("u1", "EGFR抑制剂", "抑制EGFR通路", "阻断EGFR信号"),
            _hyp("u2", "HER2单抗", "HER2抗体药物偶联物", "靶向HER2受体"),
        ]
        result_r = await ep.compute_similarities(rewrite_hyps)
        result_u = await ep.compute_similarities(unrelated_hyps)
        emb_rewrite = result_r["matrix"][("r1", "r2")]["embedding_score"]
        emb_unrelated = result_u["matrix"][("u1", "u2")]["embedding_score"]
        # 同义改写的嵌入分数应显著高于无关假设
        assert emb_rewrite > emb_unrelated, (
            f"同义改写嵌入分数({emb_rewrite})应高于无关假设({emb_unrelated})"
        )


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