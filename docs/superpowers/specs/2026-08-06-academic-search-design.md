# 后端学术检索统一工具 — 设计文档

> Date: 2026-08-06
> Author: user + assistant
> Status: APPROVED

## Background

P2 "表征与保真"阶段的后端缺口。已有 4 个学术客户端(biorxiv_real.py/arxiv_real.py/semantic_scholar_real.py/crossref_real.py)和统一的 AcademicClientBase 接口(AcademicPaper dataclass + search() 方法),但缺少:

1. 统一的学术检索 Agent 工具(覆盖 pubmed + 4 个新源)
2. 聚合检索 REST 端点(并行多源查询 + 去重排序)

现有 search_ncbi 工具只覆盖 PubMed/ClinVar/Gene/Protein/Nucleotide,无法检索 bioRXiv/arXiv 等预印本库。

## In scope

1. AcademicSearchClient —— 统一封装 5 个数据源客户端,提供单源查询 + 并行聚合查询 + 去重
2. POST /api/v1/knowledge/academic-search —— 聚合检索 REST 端点
3. SearchAcademicTool —— Agent 工具注册(search_academic)
4. Backward compat —— search_ncbi 保留,pubmed 分支委托给 AcademicSearchClient
5. 测试 —— 单元测试 + 契约测试,全走 mock,不发真实网络请求

## Out of scope

- 前端证据溯源展示(后续任务)
- 用户干预/重新执行(后续任务)
- WebSocket 实时推送(保持轮询模式)
- ScienceDirect/Elsevier 等付费源
- 全文 PDF 获取(仅元数据 + 摘要)

## Architecture

调用方: SearchAcademicTool + POST /knowledge/academic-search + search_ncbi(pubmed)
  → AcademicSearchClient (backend/app/services/analyzer/)
    → pubmed: RealNcbiClient.search_pubmed()
    → biorxiv: RealBiorxivClient.search()
    → arxiv: RealArxivClient.search()
    → semantic_scholar: RealSemanticScholarClient.search()
    → crossref: RealCrossrefClient.search()

数据模型: 复用 AcademicPaper (dataclass in app/clients/base.py)

## Design

### 1. AcademicSearchClient
路径: backend/app/services/analyzer/academic_search_client.py

- VALID_SOURCES = ["pubmed","biorxiv","arxiv","semantic_scholar","crossref"]
- pubmed lazy 加载 (get_ncbi_client 依赖注入)
- search(source, query, limit=10, year_from, year_to) -> List[AcademicPaper]
- search_all(query, sources, limit_per_source, ...) -> Dict[str,List[AcademicPaper]]
  - asyncio.gather (*tasks, return_exceptions=True) 并行
  - 单源异常/超时(10s)降级返回空列表
- deduplicate(papers) -> 按 DOI 去重(保留 relevance_score 最高)
- sort_by_relevance(papers) -> relevance_score 降序(None 排最后),次按 published_date 降序

### 2. 聚合检索端点
路径: backend/app/api/v1/endpoints/knowledge.py (追加)

AcademicSearchRequest:
- query: str (min_length=1, max_length=500)
- sources: List[str] (default 5 源)
- limit_per_source: int (1-50, default 10)
- year_from, year_to: Optional[int]
- deduplicate: bool = True

AcademicSearchResponse:
- query, sources_queried, total_hits: Dict[str,int]
- papers: List[AcademicPaper], search_time_ms: int

鉴权: get_current_user (与 gene/variant/chembl 一致)
不写 ReasoningTrace (REST 端点不注入)

### 3. SearchAcademicTool
路径: backend/app/services/agent/tools/academic_search.py

- name = "search_academic"
- parameters: query(必填)/source(必填,enum 5 源)/limit(选填,default 10)/year_from/year_to(选填)
- side_effects = False, required_role = UserRole.RESEARCHER
- execute: AcademicSearchClient().search() -> ToolResult.ok
- 注册到 registry.py

### 4. Backward Compat
search_ncbi 保留, db=="pubmed" 分支改调 AcademicSearchClient().search("pubmed",...)
其余分支(clinvar/gene/protein/nucleotide)不变

## Testing Plan

单元测试:
- tests/test_academic_search_client.py (7 例: 单源/并行/超时/异常/去重/排序/非法源)
- tests/test_academic_search_tool.py (4 例: 注册/参数校验/调用/权限)

契约测试 (ASGITransport + 内存 SQLite):
- tests/test_academic_search_endpoint.py (8 例: 200 单源/多源/422 空 query/未知 source/超 limit/去重开/关/部分源失败)

全走 mock,不发真实网络。