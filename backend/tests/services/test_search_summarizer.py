"""搜索结果 域名去重 + Top-N + 摘要器 测试"""
from app.services.search.base import SearchResult


def _sr(url, title="t", snippet="s", pos=1, src="duckduckgo"):
    r = SearchResult(url=url, title=title, snippet=snippet, source=src)
    r.position = pos
    return r


class TestDomainDedup:
    def test_aggregate_prefers_higher_score_same_domain(self):
        from app.services.search.aggregator import MultiEngineAggregator
        agg = MultiEngineAggregator(engines=[])
        group = [
            _sr("https://pubmed.ncbi.nlm.nih.gov/123", pos=3, title="A"),
            _sr("https://pubmed.ncbi.nlm.nih.gov/456", pos=1, title="B"),
        ]
        result = agg._aggregate(group)
        assert len(result) == 1
        assert result[0].position == 1

    def test_apply_domain_n_and_truncate_top5(self):
        """同域名最多 2 条，全局最多 5 条"""
        from app.services.search.aggregator import apply_domain_limit_and_truncate
        results = [
            _sr("https://pubmed.ncbi.nlm.nih.gov/1"),
            _sr("https://pubmed.ncbi.nlm.nih.gov/2"),
            _sr("https://pubmed.ncbi.nlm.nih.gov/3"),
            _sr("https://nature.com/articles/1"),
            _sr("https://nature.com/articles/2"),
            _sr("https://nature.com/articles/3"),
            _sr("https://arxiv.org/abs/1"),
            _sr("https://cell.com/1"),
            _sr("https://science.org/1"),
            _sr("https://wikipedia.org/1"),
        ]
        out = apply_domain_limit_and_truncate(results, per_domain=2, total=5)
        assert len(out) == 5
        pubmed = [r for r in out if "pubmed.ncbi.nlm.nih.gov" in r.url]
        nature = [r for r in out if "nature.com" in r.url]
        assert len(pubmed) == 2
        assert len(nature) == 2


class TestSearchSummarizer:
    def test_summarize_extracts_key_points(self):
        from app.services.search.summarizer import SearchSummarizer
        results = [
            _sr("https://a.com/1", title="Phase III trial of Osimertinib in NSCLC",
                snippet="In EGFRm NSCLC osimertinib 80mg qd PFS 18.9m vs SOC 10.2m HR 0.46"),
            _sr("https://b.com/2", title="EGFR TKI resistance mechanisms",
                snippet="T790M and C797S account for ~60% of osimertinib resistance in NSCLC"),
            _sr("https://c.com/3", title="Biomarker-guided trial",
                snippet="Liquid biopsy ctDNA EGFRm detection 92% sensitivity paired with tissue"),
        ]
        s = SearchSummarizer().summarize(results, max_characters=400)
        assert "Osimertinib" in s or "osimertinib" in s
        assert len(s) <= 420
        assert s.count("\n- ") >= 2 or s.count("1.") >= 1

    def test_summarize_empty_is_empty_string(self):
        from app.services.search.summarizer import SearchSummarizer
        assert SearchSummarizer().summarize([]) == ""
