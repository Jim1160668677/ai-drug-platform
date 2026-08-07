# Academic Search — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 实现统一学术检索客户端、聚合 REST 端点、Agent 工具注册,覆盖 PubMed/bioRxiv/arXiv/Semantic Scholar/CrossRef 5 个数据源,复用现有 AcademicClientBase 接口。

**Architecture:** AcademicSearchClient 封装 5 个已有 AcademicClientBase 实现(asyncio.gather 并行 + 单源超时/异常降级 + DOI 去重 + 相关性排序);knowledge.py 追加聚合端点;SearchAcademicTool 注册为 agent 工具;search_ncbi 保留,pubmed 分支委托给 AcademicSearchClient。

**Tech Stack:** FastAPI + SQLAlchemy async + Pydantic + asyncio + httpx(已有)

## Global Constraints

- 复用 `app/clients/base.py` 的 `AcademicClientBase` / `AcademicPaper` 接口
- 复用现有 5 个 Real*Client,不修改其内部实现(除必要的 import 调整)
- 全测试走 mock,不发真实网络请求
- search_ncbi 必须保留(向后兼容),pubmed 分支委托给 AcademicSearchClient
- 工具注册追加到 registry.py,不破坏现有工具

---

### Task 1: AcademicSearchClient — 单源查询 + 并行聚合

**Files:**
- Create: `backend/app/services/analyzer/academic_search_client.py`
- Test: `backend/tests/test_academic_search_client.py`

**Interfaces:**
- Consumes: `RealBiorxivClient`, `RealArxivClient`, `RealSemanticScholarClient`, `RealCrossrefClient`, `get_ncbi_client` (lazy)
- Produces: `AcademicSearchClient.search()`, `AcademicSearchClient.search_all()`, `AcademicSearchClient.deduplicate()`, `AcademicSearchClient.sort_by_relevance()`

- [ ] **Step 1: Write the failing test**

Create `backend/tests/test_academic_search_client.py`:

```python
import pytest
from unittest.mock import AsyncMock, patch
from app.services.analyzer.academic_search_client import AcademicSearchClient
from app.clients.base import AcademicPaper

def make_paper(doi="doi-1", title="Test", source="biorxiv", score=0.8):
    return AcademicPaper(title=title, authors=["A"], source=source, doi=doi, relevance_score=score, year=2024)

@pytest.fixture
def client():
    with patch("app.services.analyzer.academic_search_client.RealBiorxivClient"), \
         patch("app.services.analyzer.academic_search_client.RealArxivClient"), \
         patch("app.services.analyzer.academic_search_client.RealSemanticScholarClient"), \
         patch("app.services.analyzer.academic_search_client.RealCrossrefClient"):
        yield AcademicSearchClient()

@pytest.mark.asyncio
async def test_search_all_parallel(client):
    papers_a = [make_paper("a", "A", "biorxiv", 0.9)]
    papers_b = [make_paper("b", "B", "arxiv", 0.7)]
    client._clients["biorxiv"].search = AsyncMock(return_value=papers_a)
    client._clients["arxiv"].search = AsyncMock(return_value=papers_b)
    client._clients["semantic_scholar"].search = AsyncMock(return_value=[])
    client._clients["crossref"].search = AsyncMock(return_value=[])
    client._clients["pubmed"].search_pubmed = AsyncMock(return_value=[])
    result = await client.search_all("cancer", ["biorxiv", "arxiv"], limit_per_source=5)
    assert "biorxiv" in result and "arxiv" in result
    assert len(result["biorxiv"]) == 1
    assert result["biorxiv"][0].doi == "a"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_academic_search_client.py -v --no-cov`
Expected: FAIL (ModuleNotFoundError)

- [ ] **Step 3: Write minimal implementation**

Create `backend/app/services/analyzer/academic_search_client.py`:

```python
import asyncio
import logging
import time
from collections import OrderedDict
from typing import Dict, List, Optional

from app.clients.base import AcademicClientBase, AcademicPaper

logger = logging.getLogger(__name__)

class AcademicSearchClient:
    """统一学术检索客户端 — 封装 5 个 AcademicClientBase 实现"""

    VALID_SOURCES = ["pubmed", "biorxiv", "arxiv", "semantic_scholar", "crossref"]

    def __init__(self):
        self._timeout_per_source = 10
        self._clients: Dict[str, AcademicClientBase] = {}
        self._pubmed_loaded = False

    def _get_pubmed(self) -> AcademicClientBase:
        if not self._pubmed_loaded:
            from app.core.deps import get_ncbi_client
            self._clients["pubmed"] = get_ncbi_client()
            self._pubmed_loaded = True
        return self._clients["pubmed"]

    def _get_client(self, source: str) -> AcademicClientBase:
        if source == "pubmed":
            return self._get_pubmed()
        if source not in self._clients:
            if source == "biorxiv":
                from app.clients.real.biorxiv_real import RealBiorxivClient
                self._clients[source] = RealBiorxivClient()
            elif source == "arxiv":
                from app.clients.real.arxiv_real import RealArxivClient
                self._clients[source] = RealArxivClient()
            elif source == "semantic_scholar":
                from app.clients.real.semantic_scholar_real import RealSemanticScholarClient
                self._clients[source] = RealSemanticScholarClient()
            elif source == "crossref":
                from app.clients.real.crossref_real import RealCrossrefClient
                self._clients[source] = RealCrossrefClient()
        return self._clients[source]

    async def search(self, source: str, query: str, limit: int = 10,
                     year_from: Optional[int] = None, year_to: Optional[int] = None) -> List[AcademicPaper]:
        if source not in self.VALID_SOURCES:
            raise ValueError(f"Unknown source: {source}. Valid: {self.VALID_SOURCES}")
        client = self._get_client(source)
        if source == "pubmed":
            return await asyncio.wait_for(
                client.search_pubmed(query=query, retmax=limit), timeout=self._timeout_per_source)
        return await asyncio.wait_for(
            client.search(query=query, limit=limit, year_from=year_from, year_to=year_to),
            timeout=self._timeout_per_source)

    async def search_all(self, query: str, sources: List[str],
                         limit_per_source: int = 10,
                         year_from: Optional[int] = None, year_to: Optional[int] = None
                         ) -> Dict[str, List[AcademicPaper]]:
        tasks = {s: asyncio.create_task(self.search(s, query, limit_per_source, year_from, year_to))
                 for s in sources}
        results: Dict[str, List[AcademicPaper]] = {}
        for source, task in tasks.items():
            try:
                results[source] = await task
            except Exception as e:
                logger.warning(f"AcademicSearchClient: source {source} failed: {e}")
                results[source] = []
        return results

    @staticmethod
    def deduplicate(papers: List[AcademicPaper]) -> List[AcademicPaper]:
        seen: OrderedDict[str, AcademicPaper] = OrderedDict()
        no_doi: List[AcademicPaper] = []
        for p in papers:
            if p.doi:
                doi_key = p.doi.lower()
                if doi_key not in seen or (p.relevance_score or 0) > (seen[doi_key].relevance_score or 0):
                    seen[doi_key] = p
            else:
                no_doi.append(p)
        return list(seen.values()) + no_doi

    @staticmethod
    def sort_by_relevance(papers: List[AcademicPaper]) -> List[AcademicPaper]:
        def key(p: AcademicPaper):
            score = p.relevance_score if p.relevance_score is not None else -1
            year = p.year or 0
            return (-score, -year)
        return sorted(papers, key=key)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_academic_search_client.py -v --no-cov`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add backend/app/services/analyzer/academic_search_client.py tests/test_academic_search_client.py
git commit -m "feat: add AcademicSearchClient with parallel multi-source query"
```

---

### Task 2: AcademicSearchClient — 超时/异常降级/去重/排序测试

**Files:**
- Modify: `backend/tests/test_academic_search_client.py` (append)
- Test: `backend/tests/test_academic_search_client.py`

**Interfaces:**
- Consumes: Task 1 AcademicSearchClient
- Produces: verified resilience behavior

- [ ] **Step 1: Write the failing tests**

Append to `backend/tests/test_academic_search_client.py`:

```python
import asyncio

@pytest.mark.asyncio
async def test_search_source_exception_does_not_block_others(client):
    good = make_paper("good", "Good", "biorxiv", 0.8)
    client._clients["biorxiv"].search = AsyncMock(return_value=[good])
    client._clients["arxiv"].search = AsyncMock(side_effect=RuntimeError("network error"))
    result = await client.search_all("test", ["biorxiv", "arxiv"])
    assert len(result["biorxiv"]) == 1
    assert result["arxiv"] == []  # degraded, not exception

@pytest.mark.asyncio
async def test_search_invalid_source_raises(client):
    with pytest.raises(ValueError, match="Unknown source"):
        await client.search("invalid_db", "test")

def test_deduplicate_by_doi(client):
    p1 = make_paper("same-doi", "Title A", "biorxiv", 0.6)
    p2 = make_paper("same-doi", "Title B", "arxiv", 0.9)
    p3 = make_paper("other", "Title C", "crossref", 0.5)
    result = client.deduplicate([p1, p2, p3])
 dois = [p.doi for p in result]
    assert "same-doi" in dois and "other" in dois
    kept = [p for p in result if p.doi == "same-doi"]
    assert len(kept) == 1 and kept[0].relevance_score == 0.9

def test_sort_by_relevance(client):
    papers = [
        make_paper("a", "A", "biorxiv", None),
        make_paper("b", "B", "arxiv", 0.9),
        make_paper("c", "C", "crossref", 0.5),
    ]
    result = AcademicSearchClient.sort_by_relevance(papers)
    assert result[0].doi == "b" and result[1].doi == "c"
    assert result[-1].doi == "a"  # None score last
```

- [ ] **Step 2: Run test to verify it passes**

Run: `pytest tests/test_academic_search_client.py -v --no-cov`
Expected: All tests PASS

- [ ] **Step 3: Commit**

```bash
git add tests/test_academic_search_client.py
git commit -m "test: add AcademicSearchClient resilience tests"
```

---

### Task 3: SearchAcademicTool — Agent 工具

**Files:**
- Create: `backend/app/services/agent/tools/academic_search.py`
- Modify: `backend/app/services/agent/tools/registry.py`
- Test: `backend/tests/test_academic_search_tool.py`

**Interfaces:**
- Consumes: Task 1 AcademicSearchClient
- Produces: `search_academic` tool registered in registry

- [ ] **Step 1: Write the failing test**

Create `backend/tests/test_academic_search_tool.py`:

```python
import pytest
from unittest.mock import AsyncMock, patch
from app.services.agent.tools.registry import ToolRegistry
from app.services.agent.tools.base import ToolContext

@pytest.fixture
def registry():
    return ToolRegistry()

def test_tool_registered(registry):
    tools = registry.list_tools()
    names = [t["name"] for t in tools]
    assert "search_academic" in names

@pytest.mark.asyncio
async def test_tool_execute(registry):
    from app.services.agent.tools.academic_search import SearchAcademicTool
    tool = SearchAcademicTool()
    fake_papers = [{"title": "Test", "doi": "x", "source": "biorxiv"}]
    with patch("app.services.agent.tools.academic_search.AcademicSearchClient") as MockClient:
        instance = MockClient.return_value
        instance.search = AsyncMock(return_value=fake_papers)
        ctx = ToolContext(user=MagicMock(), db=MagicMock(), run_id=None)
        result = await tool.execute({"query": "cancer", "source": "biorxiv", "limit": 5}, ctx)
    assert result.success
    assert "articles" in result.data
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_academic_search_tool.py -v --no-cov`
Expected: FAIL (module not found)

- [ ] **Step 3: Write minimal implementation**

Create `backend/app/services/agent/tools/academic_search.py`:

```python
import logging
from typing import Any, Dict

from app.core.security import UserRole
from app.services.agent.tools.base import AgentTool, ToolContext, ToolParameter, ToolResult

logger = logging.getLogger(__name__)

class SearchAcademicTool(AgentTool):
    name = "search_academic"
    description = (
        "跨学术数据库检索文献。支持 PubMed、bioRxiv、arXiv、Semantic Scholar、CrossRef。"
        "返回标题/作者/摘要/DOI/发表日期/来源/相关性分数。"
    )
    parameters = [
        ToolParameter("query", "string", "检索词(如 'EGFR lung cancer')", required=True),
        ToolParameter("source", "string", "数据源", required=True,
                      enum=["pubmed", "biorxiv", "arxiv", "semantic_scholar", "crossref"]),
        ToolParameter("limit", "integer", "返回数(1-50)", required=False, default=10),
        ToolParameter("year_from", "integer", "起始年份", required=False),
        ToolParameter("year_to", "integer", "截止年份", required=False),
    ]
    side_effects = False
    required_role = UserRole.RESEARCHER

    async def execute(self, params: Dict[str, Any], ctx: ToolContext) -> ToolResult:
        from app.services.analyzer.academic_search_client import AcademicSearchClient
        client = AcademicSearchClient()
        query = params["query"]
        source = params["source"]
        limit = min(max(params.get("limit", 10), 1), 50)
        year_from = params.get("year_from")
        year_to = params.get("year_to")
        try:
            papers = await client.search(source, query, limit, year_from, year_to)
            return ToolResult.ok(
                data={"source": source, "query": query, "total": len(papers), "articles": [
                    {"title": p.title, "authors": p.authors, "abstract": p.abstract,
                     "doi": p.doi, "source": p.source, "year": p.year,
                     "url": p.url, "relevance_score": p.relevance_score} for p in papers
                ]},
                display={"type": "literature_list", "payload": {"articles": [
                    {"title": p.title, "authors": p.authors, "doi": p.doi, "source": p.source}
                    for p in papers[:limit]
                ]}},
            )
        except Exception as e:
            logger.error(f"search_academic failed: {e}", exc_info=True)
            return ToolResult.fail(error=str(e))
```

Modify `backend/app/services/agent/tools/registry.py`:
- Import: `from app.services.agent.tools.academic_search import SearchAcademicTool`
- Append to `register_all()` tool list: `SearchAcademicTool()`

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_academic_search_tool.py -v --no-cov`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add backend/app/services/agent/tools/academic_search.py backend/app/services/agent/tools/registry.py tests/test_academic_search_tool.py
git commit -m "feat: register search_academic agent tool"
```

---

### Task 4: 聚合检索 REST 端点

**Files:**
- Modify: `backend/app/api/v1/endpoints/knowledge.py`
- Test: `backend/tests/test_academic_search_endpoint.py`

**Interfaces:**
- Consumes: Task 1 AcademicSearchClient
- Produces: `POST /api/v1/knowledge/academic-search`

- [ ] **Step 1: Write the failing contract test**

Create `backend/tests/test_academic_search_endpoint.py` (复用 test_api_contract.py 的 fixture 模式):

```python
import pytest
from unittest.mock import AsyncMock, patch
from httpx import ASGITransport, AsyncClient
from app.main import app

@pytest.fixture
def anyio_backend():
    return "asyncio"

def make_paper_dict(doi="doi-1", title="Test Cancer Drug", source="biorxiv", score=0.85, year=2024):
    return {"title": title, "authors": ["Smith J"], "abstract": "About cancer", "doi": doi,
            "source": source, "year": year, "url": f"https://x.org/{doi}", "relevance_score": score}

@pytest.mark.asyncio
@patch("app.api.v1.endpoints.knowledge.AcademicSearchClient")
async def test_200_single_source(MockClient, auth_headers):
    instance = MockClient.return_value
    instance.search_all = AsyncMock(return_value={"biorxiv": [
        make_paper_dict("d1", "Paper One", "biorxiv", 0.9),
        make_paper_dict("d2", "Paper Two", "biorxiv", 0.7),
    ]})
    instance.deduplicate = AsyncMock(side_effect=lambda x: x)
    instance.sort_by_relevance = AsyncMock(side_effect=lambda x: x)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.post("/api/v1/knowledge/academic-search",
                                json={"query": "cancer", "sources": ["biorxiv"], "limit_per_source": 10},
                                headers=auth_headers)
    assert resp.status_code == 200
    body = resp.json()["data"]
    assert body["query"] == "cancer"
    assert body["total_hits"]["biorxiv"] == 2
    assert len(body["papers"]) == 2
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_academic_search_endpoint.py -v --no-cov`
Expected: FAIL (route not found / 404)

- [ ] **Step 3: Write minimal implementation**

Modify `backend/app/api/v1/endpoints/knowledge.py`:
- Add imports: `from pydantic import BaseModel, Field`, `from typing import List, Optional`
- Add request/response models and route

```python
class AcademicSearchRequest(BaseModel):
    query: str = Field(..., min_length=1, max_length=500)
    sources: List[str] = Field(default=["pubmed","biorxiv","arxiv","semantic_scholar","crossref"])
    limit_per_source: int = Field(default=10, ge=1, le=50)
    year_from: Optional[int] = Field(default=None, ge=1900, le=2100)
    year_to: Optional[int] = Field(default=None, ge=1900, le=2100)
    deduplicate: bool = True

class AcademicSearchResponse(BaseModel):
    query: str
    sources_queried: List[str]
    total_hits: Dict[str, int]
    papers: List[dict]
    search_time_ms: int

@router.post("/academic-search", response_model=StandardResponse, summary="学术资源聚合检索(5源并行)")
async def academic_search(payload: AcademicSearchRequest, current_user=Depends(get_current_user)):
    from app.services.analyzer.academic_search_client import AcademicSearchClient
    t0 = time.time()
    client = AcademicSearchClient()
    raw = await client.search_all(payload.query, payload.sources, payload.limit_per_source,
                                 payload.year_from, payload.year_to)
    papers = [p for plist in raw.values() for p in plist]
    total_hits = {src: len(plist) for src, plist in raw.items()}
    if payload.deduplicate:
        papers = client.deduplicate(papers)
    papers = AcademicSearchClient.sort_by_relevance(papers)
    elapsed = int((time.time() - t0) * 1000)
    return success_response(AcademicSearchResponse(
        query=payload.query, sources_queried=payload.sources, total_hits=total_hits,
        papers=[p.model_dump() for p in papers], search_time_ms=elapsed
    ).model_dump())
```

Need to add `import time` and `Dict` to knowledge.py imports.

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_academic_search_endpoint.py -v --no-cov`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add backend/app/api/v1/endpoints/knowledge.py tests/test_academic_search_endpoint.py
git commit -m "feat: add POST /knowledge/academic-search aggregation endpoint"
```

---

### Task 5: 契约测试补充(422/去重/部分源失败)

**Files:**
- Modify: `backend/tests/test_academic_search_endpoint.py` (append)

**Interfaces:**
- Consumes: Task 4 endpoint
- Produces: verified contract behavior

- [ ] **Step 1: Write additional tests**

Append to `backend/tests/test_academic_search_endpoint.py`:

```python
@pytest.mark.asyncio
@patch("app.api.v1.endpoints.knowledge.AcademicSearchClient")
async def test_420_empty_query(MockClient, auth_headers):
    instance = MockClient.return_value
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.post("/api/v1/knowledge/academic-search",
                                json={"query": "", "sources": ["biorxiv"]}, headers=auth_headers)
    assert resp.status_code == 422

@pytest.mark.asyncio
@patch("app.api.v1.endpoints.knowledge.AcademicSearchClient")
async def test_422_limit_exceeded(MockClient, auth_headers):
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.post("/api/v1/knowledge/academic-search",
                                json={"query": "cancer", "sources": ["biorxiv"], "limit_per_source": 100},
                                headers=auth_headers)
    assert resp.status_code == 422

@pytest.mark.asyncio
@patch("app.api.v1.endpoints.knowledge.AcademicSearchClient")
async def test_partial_source_failure(MockClient, auth_headers):
    """一个源失败不影响其他源"""
    instance = MockClient.return_value
    async def fake_search_all(query, sources, **kw):
        result = {}
        for s in sources:
            if s == "arxiv":
                raise RuntimeError("arxiv timeout")
            result[s] = [make_paper_dict(f"d-{s}", f"Paper {s}", s)]
        return result
    instance.search_all = AsyncMock(side_effect=fake_search_all)
    instance.deduplicate = AsyncMock(side_effect=lambda x: x)
    instance.sort_by_relevance = AsyncMock(side_effect=lambda x: x)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.post("/api/v1/knowledge/academic-search",
                                json={"query": "cancer", "sources": ["biorxiv","arxiv"], "deduplicate": False},
                                headers=auth_headers)
    assert resp.status_code == 200
    body = resp.json()["data"]
    assert body["total_hits"]["biorxiv"] == 1
    assert body["total_hits"]["arxiv"] == []  # degraded
```

- [ ] **Step 2: Run test to verify it passes**

Run: `pytest tests/test_academic_search_endpoint.py -v --no-cov`
Expected: All PASS

- [ ] **Step 3: Commit**

```bash
git add tests/test_academic_search_endpoint.py
git commit -m "test: add academic-search endpoint contract tests"
```

---

### Task 6: Backward Compat — search_ncbi pubmed 委托

**Files:**
- Modify: `backend/app/services/agent/tools/ncbi.py` (pubmed branch only)

**Interfaces:**
- Consumes: Task 1 AcademicSearchClient
- Produces: search_ncbi.pubmed delegates to AcademicSearchClient

- [ ] **Step 1: Modify the pubmed branch**

In `backend/app/services/agent/tools/ncbi.py`, replace the `db == "pubmed"` branch body:

```python
elif db == "pubmed":
    from app.services.analyzer.academic_search_client import AcademicSearchClient
    asc = AcademicSearchClient()
    papers = await asc.search("pubmed", query=query, limit=retmax)
    results = [
        {"title": p.title, "authors": p.authors, "abstract": p.abstract,
         "doi": p.doi, "source": p.source, "year": p.year, "url": p.url}
        for p in papers
    ]
    return ToolResult.ok(
        data={"db": db, "query": query, "total": len(results), "articles": results},
        display={"type": "literature_list", "payload": {"articles": results[:retmax]}},
    )
```

- [ ] **Step 2: Run existing ncbi tests**

Run: `pytest tests/test_agent_tools_ncbi.py -v --no-cov` (or equivalent existing ncbi test)
Expected: All PASS (no regression)

- [ ] **Step 3: Commit**

```bash
git add backend/app/services/agent/tools/ncbi.py
git commit -m "refactor: search_ncbi pubmed branch delegates to AcademicSearchClient"
```

---

### Task 7: 全量回归验证

**Files:** none (verification only)

- [ ] **Step 1: Run academic-related tests**

Run: `pytest tests/test_academic_search_client.py tests/test_academic_search_tool.py tests/test_academic_search_endpoint.py tests/test_tier_routing.py -v --no-cov`
Expected: All PASS

- [ ] **Step 2: Run knowledge + ncbi related tests**

Run: `pytest tests/test_knowledge.py tests/test_agent_tools*.py -v --no-cov`
Expected: All PASS

- [ ] **Step 3: Run full backend regression**

Run: `pytest tests/ --no-cov -q`
Expected: 0 failed