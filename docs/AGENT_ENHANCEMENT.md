# Agent 增强功能文档

> 本文档描述 AI 药物研发平台近期新增的三大功能模块：(1) NCBI 数据库接口集成；(2) Agent 自主决策能力增强；(3) 网络搜索集成。所有功能均提供完整的单元测试和集成测试，覆盖率 ≥80%。

---

## 一、功能总览

### 1.1 新增能力矩阵

| 模块 | 能力 | 默认开关 | 配置项前缀 |
|---|---|---|---|
| NCBI 接口 | PubMed/ClinVar/Gene/Protein 数据库检索 | 自动（Mock/Real） | `NCBI_*` |
| Agent 反思 | 工具失败后自动分析原因并重试 | ✅ 启用 | `AGENT_USE_REFLECTION` |
| Agent DAG | 多步骤任务按拓扑层并行执行 | ❌ 关闭（可选启用） | `AGENT_USE_DAG_EXECUTOR` |
| Agent 盲区检测 | 连续无结果时自动触发网络搜索 | ✅ 启用 | `AGENT_USE_KNOWLEDGE_GAP_DETECTION` |
| Agent 工具质量 | 跟踪工具成功率/耗时，推荐最优工具 | ✅ 启用 | `AGENT_TOOL_QUALITY_TRACKING` |
| 网络搜索 | DuckDuckGo + Serper + Brave 多引擎聚合 | 自动（按可用性） | `WEB_SEARCH_*` |
| 网页抓取 | HTML/PDF 正文提取（trafilatura + pypdf） | ✅ 启用 | `WEB_FETCH_*` |

### 1.2 工具总数

工具注册中心共 **19 个工具**（原 16 个 + 新增 3 个）：

| 工具组 | 工具名 | 新增 | 权限角色 |
|---|---|---|---|
| 知识 | `search_ncbi` | ✅ | RESEARCHER 及以上 |
| 知识 | `web_search` | ✅ | RESEARCHER 及以上 |
| 知识 | `fetch_web_page` | ✅ | RESEARCHER 及以上 |

---

## 二、NCBI 数据库接口集成

### 2.1 架构设计

采用与现有 `ChEmblClient`/`MyGeneClient` 一致的 **ABC + Mock/Real 双模式**架构：

```
app/clients/
├── base.py            # NcbiClient 抽象基类
├── real/
│   └── ncbi_real.py   # RealNcbiClient（真实 E-utilities 调用）
├── mock/
│   └── ncbi_mock.py   # MockNcbiClient（预置数据集）
└── deps.py            # get_ncbi_client() 工厂
```

### 2.2 核心接口

`NcbiClient` 抽象基类定义统一的 E-utilities 接口：

| 方法 | 用途 | NCBI API |
|---|---|---|
| `esearch(db, term, retmax)` | 搜索数据库，返回 ID 列表 | `esearch.fcgi` |
| `esummary(db, ids)` | 获取条目摘要 | `esummary.fcgi` |
| `efetch(db, ids, rettype)` | 获取完整记录（FASTA/摘要） | `efetch.fcgi` |
| `elink(dbfrom, db, id)` | 跨库链接（gene → pubmed） | `elink.fcgi` |

高层封装方法（子类共享）：

| 方法 | 用途 |
|---|---|
| `search_pubmed(query, retmax)` | PubMed 文献检索（esearch + esummary） |
| `fetch_gene_info(gene_symbol)` | 基因信息查询（gene db） |
| `fetch_clinvar_variants(gene, retmax)` | ClinVar 致病变异查询 |
| `fetch_sequences(ids, db)` | FASTA 序列获取（protein/nucleotide） |

### 2.3 Real 客户端特性

`RealNcbiClient`（[backend/app/clients/real/ncbi_real.py](file:///g:/软件开发/AI药物/backend/app/clients/real/ncbi_real.py)）的关键能力：

- **API Key 注入**：若 `NCBI_API_KEY` 非空，每次请求自动附加 `api_key` 参数，速率限制从 3 req/s 提升到 10 req/s
- **令牌桶限流**：基于 `asyncio.Semaphore` 实现，无 Key 时 3 req/s，有 Key 时 10 req/s
- **指数退避重试**：429/5xx 自动重试，间隔 1s/2s/4s，最多 `NCBI_MAX_RETRIES` 次（默认 3）
- **缓存层**：复用 `app/services/knowledge/data_cache.py` 的 `get_cached/set_cached`，TTL 默认 7 天
- **错误降级**：网络异常返回空结果（不抛异常），业务层可降级处理
- **连接池复用**：`httpx.AsyncClient` 单例，避免每次请求建立新连接

### 2.4 配置项

在 `backend/app/core/config.py` 中：

```python
# ========== NCBI E-utilities ==========
NCBI_BASE_URL: str = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils"
NCBI_API_KEY: str = ""                       # 可选，提升速率限制到 10 req/s
NCBI_RATE_LIMIT_RPS: int = 3                 # 无 API Key 时的速率限制
NCBI_CACHE_TTL_DAYS: int = 7                 # 缓存有效期
NCBI_MAX_RETRIES: int = 3                    # 最大重试次数（指数退避 1s/2s/4s）
NCBI_TIMEOUT_SEC: int = 30                   # 请求超时
```

### 2.5 获取 NCBI API Key

1. 访问 https://www.ncbi.nlm.nih.gov/account/settings/
2. 登录 NCBI 账号（需注册）
3. 在 "API Key Management" 创建新 Key
4. 将 Key 写入 `.env` 文件：

```bash
NCBI_API_KEY=your_api_key_here
```

### 2.6 Agent 工具使用

通过 `search_ncbi` 工具调用（Agent 自动调用，也可通过 API 手动触发）：

```python
# 通过 Agent 调用
# 用户问："查询 EGFR 相关的 PubMed 文献"
# Agent 自动调用：
search_ncbi(db="pubmed", query="EGFR inhibitor", retmax=5)

# 用户问："TP53 基因有哪些致病变异？"
search_ncbi(db="clinvar", query="TP53", retmax=10)

# 用户问："获取 EGFR 基因信息"
search_ncbi(db="gene", query="EGFR")

# 用户问："获取 P53 蛋白序列"
search_ncbi(db="protein", query="NP_000537.3", rettype="fasta")
```

支持的数据库：

| db 值 | 用途 | 返回字段 |
|---|---|---|
| `pubmed` | 文献检索 | PMID/标题/摘要/作者/期刊/发表日期 |
| `clinvar` | 致病变异 | HGVS/临床意义/评审星级/条件/基因 |
| `gene` | 基因信息 | symbol/全名/染色体/Summary/GeneID |
| `protein` | 蛋白序列 | FASTA 格式序列 |
| `nucleotide` | 核酸序列 | FASTA 格式序列 |

### 2.7 与现有代码的集成

`evidence_chain.py` 中的 `_query_clinvar_by_gene` 已重构为调用 `NcbiClient.fetch_clinvar_variants()`，删除内联 httpx 调用（约 100 行 → 30 行）。`clinvar_client.py` 的 `ClinvarClient` 内部委托 `NcbiClient`，保留旧 API 签名以兼容现有调用方。

---

## 三、Agent 功能增强

### 3.1 整体架构

```
AgentEngine
├── TaskPlanner          任务规划（生成 DAG）
├── DagExecutor         DAG 并行执行器（可选）
├── Reflector           工具失败反思器
├── ToolQualityTracker  工具质量跟踪器
├── KnowledgeGapDetector 知识盲区检测器
├── SessionManager      会话管理
├── ProgressManager     进度推送
└── AuditLogger         审计日志
```

### 3.2 反思与重规划（Reflector）

**文件**：[backend/app/services/agent/reflection.py](file:///g:/软件开发/AI药物/backend/app/services/agent/reflection.py)

**触发条件**：工具调用返回 `ToolResult.fail()` 时。

**工作流程**：

1. 启发式分类：根据错误信息关键字分类（参数错误/权限不足/网络异常/数据不存在/工具内部错误/超时）
2. 生成恢复策略：
   - `RETRY_WITH_FIXED_PARAMS`：修正参数后重试
   - `SWITCH_TOOL`：切换到备选工具
   - `GIVE_UP`：放弃重试，基于现有信息生成答案
   - `ESCALATE_TO_USER`：升级到用户处理
3. 若启用 LLM 深度分析，调用 `REFLECTION_PROMPT` 让 LLM 生成更精准的恢复建议
4. 重试次数限制：默认最多 2 次（`AGENT_REFLECTION_MAX_RETRIES`），超过后强制放弃

**配置项**：

```python
AGENT_USE_REFLECTION: bool = True             # 工具失败反思重试
AGENT_REFLECTION_MAX_RETRIES: int = 2         # 反思最大重试次数（防死循环）
```

**示例**：

```python
# 工具失败：discover_targets(project_id="") → "缺少必填参数: project_id"
# Reflector 分析：
#   error_category = PARAM_ERROR
#   is_retryable = True
#   recovery_strategy = RETRY_WITH_FIXED_PARAMS
#   suggested_params_hint = "project_id 必填，请从项目上下文获取"
#   observation_for_llm = "工具 discover_targets 因参数错误失败，建议补充 project_id 后重试"
# Agent 收到 observation，在下一步调整参数重试
```

### 3.3 DAG 并行执行器（DagExecutor）

**文件**：[backend/app/services/agent/dag_executor.py](file:///g:/软件开发/AI药物/backend/app/services/agent/dag_executor.py)

**触发条件**：Planner 输出的 `parallel_layers` 非空且 `AGENT_USE_DAG_EXECUTOR=True`。

**工作流程**：

1. 按拓扑层执行：同层步骤用 `asyncio.gather` 并行，层间串行（依赖上层结果）
2. 参数依赖解析：`{"gene": "${step_1.gene_symbol}"}` 自动从上游结果取值
3. 失败传播：上层失败时下层同分支跳过
4. 并发控制：同层最大并发 5（`max_concurrency`），避免事件循环阻塞
5. 进度推送：每步开始/完成时推送 WebSocket 事件

**配置项**：

```python
AGENT_USE_DAG_EXECUTOR: bool = False          # DAG 并行执行开关（默认关闭，逐步启用）
```

**参数模板语法**：

```python
# Planner 输出的 plan：
plan = PlannerOutput(
    steps=[
        PlanStep(id="s1", tool="search_ncbi", args={"query": "EGFR"}),
        PlanStep(
            id="s2",
            tool="discover_targets",
            args={"target_gene": "${s1.gene_symbol}"},  # 引用 s1 的结果
            depends_on=["s1"],
        ),
    ],
    parallel_layers=[["s1"], ["s2"]],
)

# DagExecutor 执行：
# 1. 执行 s1 → 返回 {"gene_symbol": "EGFR", ...}
# 2. 解析模板：${s1.gene_symbol} → "EGFR"
# 3. 执行 s2 with target_gene="EGFR"
```

### 3.4 知识盲区检测（KnowledgeGapDetector）

**文件**：[backend/app/services/agent/knowledge_gap.py](file:///g:/软件开发/AI药物/backend/app/services/agent/knowledge_gap.py)

**触发条件**：连续 `AGENT_KNOWLEDGE_GAP_THRESHOLD`（默认 2）步工具返回空结果或"未找到"。

**工作流程**：

1. 记录每步工具的观察结果（`observe()` 方法）
2. 启发式检测：
   - 连续空结果（`total=0`/`count=0`/"未找到"/"no results"）
   - 循环推理检测（同样工具+参数重复调用）
3. 若启用 LLM 深度检测，调用 `KNOWLEDGE_GAP_DETECTION_PROMPT` 让 LLM 判断是否为盲区
4. 检测到盲区时，生成建议的搜索查询词，注入到下一步 ReAct prompt：
   ```
   知识库无相关结果，建议使用 web_search 工具检索：
   搜索词建议："{suggested_search_query}"
   ```
5. 降级：检测 3 次后仍未解决 → 进入 Final Answer，明确告知用户"知识库与网络搜索均无结果"

**盲区类型**：

| GapType | 含义 |
|---|---|
| `NO_RESULTS` | 连续多次工具返回空结果 |
| `IRRELEVANT_RESULTS` | 工具调用与用户问题无明显关联 |
| `CIRCULAR_REASONING` | 在兜圈子（重复调用同样工具+参数） |
| `NONE` | 非盲区 |

**配置项**：

```python
AGENT_USE_KNOWLEDGE_GAP_DETECTION: bool = True  # 知识盲区自动触发网络搜索
AGENT_KNOWLEDGE_GAP_THRESHOLD: int = 2         # 连续无结果步数触发阈值
```

### 3.5 工具质量跟踪（ToolQualityTracker）

**文件**：[backend/app/services/agent/tool_quality.py](file:///g:/软件开发/AI药物/backend/app/services/agent/tool_quality.py)

**设计**：单例模式（`get_tool_quality_tracker()`），内存存储，TTL 默认 7 天。

**跟踪指标**：

| 指标 | 含义 |
|---|---|
| `total_calls` | 总调用次数 |
| `success_count` | 成功次数 |
| `failure_count` | 失败次数 |
| `success_rate` | 成功率（0-1） |
| `avg_duration_ms` | 平均耗时 |
| `min/max_duration_ms` | 最小/最大耗时 |
| `last_error` | 最近错误信息 |
| `last_called_at` | 最近调用时间 |

**质量评分公式**：

```
quality_score = 0.7 * success_rate + 0.3 * latency_score
# latency_score: avg_duration_ms 越低分越高（线性归一化到 0-1）
```

**工具推荐**：

```python
# 当有多个功能相似的工具时，ToolQualityTracker 推荐最优工具
ranked = await tracker.rank_tools(["search_literature", "search_ncbi", "web_search"])
# 返回按 quality_score 降序排列的工具列表
```

**配置项**：

```python
AGENT_TOOL_QUALITY_TRACKING: bool = True      # 工具质量跟踪开关
AGENT_TOOL_QUALITY_TTL_DAYS: int = 7          # 工具质量数据保留时长
```

### 3.6 Engine 集成

`AgentEngine.__init__` 中根据配置初始化增强组件（均支持独立开关，降级兼容）：

```python
class AgentEngine:
    def __init__(self, ...):
        # 1. 工具失败反思器
        self.reflector = Reflector(llm_router=llm_router) if settings.AGENT_USE_REFLECTION else None

        # 2. DAG 并行执行器
        self.dag_executor = DagExecutor(registry=registry) if settings.AGENT_USE_DAG_EXECUTOR else None

        # 3. 工具质量跟踪器
        self.tool_quality = get_tool_quality_tracker() if settings.AGENT_TOOL_QUALITY_TRACKING else None

        # 4. 知识盲区检测器
        self.gap_detector = KnowledgeGapDetector(llm_router=llm_router) if settings.AGENT_USE_KNOWLEDGE_GAP_DETECTION else None
```

工具调用流程的增强点：

1. **工具选择前**：调用 `tool_quality.recommend_tool()` 优先选择质量评分高的工具
2. **工具执行后**：调用 `tool_quality.record()` 记录指标
3. **工具失败时**：调用 `reflector.reflect()` 生成恢复策略
4. **每步观察后**：调用 `gap_detector.observe()` 记录观察
5. **盲区检测触发**：调用 `gap_detector.detect()` 判断是否为盲区，若是则注入网络搜索建议

---

## 四、网络搜索集成

### 4.1 架构设计

```
app/services/search/
├── base.py            # SearchEngine ABC + SearchResult + URL 归一化
├── duckduckgo.py      # DuckDuckGoEngine（免费，无 API Key）
├── serper.py          # SerperEngine（Google 代理，免费 2500 次/月）
├── brave.py           # BraveSearchEngine（免费 2000 次/月）
├── aggregator.py      # MultiEngineAggregator（多引擎聚合）
└── fetcher.py         # WebPageFetcher（网页正文提取）
```

### 4.2 多引擎聚合器（MultiEngineAggregator）

**文件**：[backend/app/services/search/aggregator.py](file:///g:/软件开发/AI药物/backend/app/services/search/aggregator.py)

**工作流程**：

1. **并发调用**：用 `asyncio.gather(return_exceptions=True)` 并发调用所有可用引擎，单引擎失败不影响整体
2. **URL 归一化去重**：
   - 去除追踪参数（`utm_*`/`fbclid`/`gclid`/`mc_cid` 等）
   - 去除 fragment（`#anchor`）
   - 同 URL 多源命中 → 合并为一条
3. **综合评分**：

```
total_score = source_weight * 0.4 + domain_authority * 0.4 + position_score * 0.2
```

| 维度 | 权重 | 说明 |
|---|---|---|
| 来源权重 | 0.4 | serper 1.0 > brave 0.9 > duckduckgo 0.8；多源命中 +0.1 |
| 域名权威性 | 0.4 | .gov/.edu/.nih.gov=10 分；arxiv/pubmed=8 分；nature/science=7 分 |
| 原始排名 | 0.2 | 第 1 名 1.0，第 10 名 0.1（线性递减） |

4. **按评分降序返回**，截断到 `max_results`

### 4.3 搜索引擎实现

#### DuckDuckGoEngine
- **库**：`duckduckgo-search`（`AsyncDDGS`）
- **API Key**：无需（免费）
- **速率限制**：1 req/s
- **Mock 模式**：`USE_MOCK=true` 时返回预置结果

#### SerperEngine
- **API**：`https://google.serper.dev/search`（POST JSON）
- **API Key**：`SERPER_API_KEY`（https://serper.dev，免费 2500 次/月）
- **特性**：Google 搜索代理，结果最权威
- **可用性**：未配置 Key 时 `is_available=False`，自动跳过

#### BraveSearchEngine
- **API**：`https://api.search.brave.com/res/v1/web/search`
- **API Key**：`BRAVE_SEARCH_API_KEY`（https://api.search.brave.com，免费 2000 次/月）
- **特性**：隐私优先，结果质量稳定
- **可用性**：未配置 Key 时 `is_available=False`，自动跳过

### 4.4 网页抓取器（WebPageFetcher）

**文件**：[backend/app/services/search/fetcher.py](file:///g:/软件开发/AI药物/backend/app/services/search/fetcher.py)

**特性**：

- **超时**：15s（`WEB_FETCH_TIMEOUT_SEC`）
- **最大响应体**：1MB
- **自动识别内容类型**：
  - HTML：`trafilatura.fetch_url` 提取正文
  - PDF：`pypdf` 提取文本
  - JSON：直接解析
- **长内容截断**：默认 5000 字符（`WEB_FETCH_MAX_CHARS`，可配置 500-20000）
- **返回结构**：`{url, title, content, content_type, fetched_at}`

### 4.5 配置项

在 `backend/app/core/config.py` 中：

```python
# ========== 网络搜索 ==========
WEB_SEARCH_ENGINE: str = "auto"              # auto / duckduckgo / serper / brave
SERPER_API_KEY: str = ""                      # https://serper.dev（免费 2500 次/月）
BRAVE_SEARCH_API_KEY: str = ""                # https://api.search.brave.com（免费 2000 次/月）
WEB_SEARCH_MAX_RESULTS: int = 10              # 单次搜索最大返回数
WEB_SEARCH_CACHE_TTL_HOURS: int = 24         # 搜索结果缓存时长
WEB_SEARCH_TIMEOUT_SEC: int = 15             # 搜索请求超时
WEB_FETCH_MAX_CHARS: int = 5000              # 网页抓取最大字符数
WEB_FETCH_TIMEOUT_SEC: int = 15              # 网页抓取超时
```

### 4.6 Agent 工具使用

新增 2 个工具（Agent 自动调用）：

#### web_search

```python
# 用户问："EGFR 抑制剂的最新临床试验进展？"
# Agent 调用：
web_search(query="EGFR inhibitor clinical trial 2026", max_results=10)

# 返回：
{
    "query": "EGFR inhibitor clinical trial 2026",
    "total": 8,
    "results": [
        {
            "title": "Osimertinib in EGFR-mutated NSCLC...",
            "url": "https://www.nejm.org/...",
            "snippet": "最新 III 期临床试验结果...",
            "source": "duckduckgo",
            "score": 0.92,
            "position": 1
        },
        ...
    ]
}
```

#### fetch_web_page

```python
# 用户问："帮我读一下这篇文献的摘要 https://www.nejm.org/..."
# Agent 调用：
fetch_web_page(url="https://www.nejm.org/...", max_chars=5000)

# 返回：
{
    "url": "https://www.nejm.org/...",
    "title": "Osimertinib in EGFR-mutated NSCLC",
    "content": "# Abstract\n\nBackground: Osimertinib is a third-generation...",
    "content_type": "html",
    "fetched_at": "2026-07-28T10:30:00Z"
}
```

### 4.7 与知识盲区检测的联动

当 `KnowledgeGapDetector` 检测到盲区时，会自动注入网络搜索建议到 ReAct prompt：

```
[系统提示] 检测到知识盲区（连续 2 步无结果），建议使用 web_search 工具检索最新信息。
建议搜索词："EGFR inhibitor clinical trial 2026"
```

Agent 在下一步会优先调用 `web_search` 获取外部信息，填补知识盲区。

---

## 五、测试验证

### 5.1 单元测试

| 测试文件 | 覆盖模块 | 测试数 | 覆盖率 |
|---|---|---|---|
| `tests/test_ncbi_client.py` | NcbiClient + Mock/Real + SearchNcbiTool | 40+ | ≥80% |
| `tests/services/test_search.py` | 搜索引擎 + 聚合器 + 抓取器 | 30+ | ≥80% |
| `tests/test_agent_reflection.py` | Reflector | 15+ | ≥80% |
| `tests/test_agent_dag_executor.py` | DagExecutor | 15+ | ≥80% |
| `tests/test_agent_tool_quality.py` | ToolQualityTracker | 15+ | ≥80% |
| `tests/test_agent_knowledge_gap.py` | KnowledgeGapDetector | 15+ | ≥80% |

### 5.2 集成测试

| 测试文件 | 覆盖场景 | 测试数 |
|---|---|---|
| `tests/test_agent_enhancements_integration.py` | 组件初始化 + 反思集成 + DAG 执行 + 工具质量记录 | 11 |

### 5.3 运行测试

```bash
cd backend

# 单元测试：NCBI 客户端
python -m pytest tests/test_ncbi_client.py -v

# 单元测试：网络搜索
python -m pytest tests/services/test_search.py -v

# 单元测试：Agent 增强
python -m pytest tests/test_agent_reflection.py tests/test_agent_dag_executor.py \
    tests/test_agent_tool_quality.py tests/test_agent_knowledge_gap.py -v

# 集成测试
python -m pytest tests/test_agent_enhancements_integration.py -v

# 覆盖率报告
python -m pytest tests/test_ncbi_client.py tests/services/test_search.py \
    tests/test_agent_reflection.py tests/test_agent_dag_executor.py \
    tests/test_agent_tool_quality.py tests/test_agent_knowledge_gap.py \
    tests/test_agent_enhancements_integration.py \
    --cov=app.clients --cov=app.services.search --cov=app.services.agent.reflection \
    --cov=app.services.agent.dag_executor --cov=app.services.agent.tool_quality \
    --cov=app.services.agent.knowledge_gap --cov-report=term-missing
```

### 5.4 Real 模式测试

Real 模式测试需配置真实 API Key，并标记 `@pytest.mark.integration`，CI 默认跳过：

```bash
# 设置 API Key
export NCBI_API_KEY=your_key
export SERPER_API_KEY=your_key

# 运行 Real 模式测试
python -m pytest tests/test_ncbi_client.py -m integration -v
```

---

## 六、配置速查

### 6.1 最小配置（开箱即用）

无需任何配置，所有功能默认使用 Mock 模式或免费引擎：

```bash
# .env 文件（可选）
USE_MOCK=true                    # Mock 模式（开发/测试）
WEB_SEARCH_ENGINE=auto           # 自动选择可用引擎（DuckDuckGo 免费）
```

### 6.2 生产配置

```bash
# .env 文件
USE_MOCK=false

# NCBI（推荐配置 API Key 提升速率限制）
NCBI_API_KEY=your_ncbi_api_key

# 网络搜索（按需配置，DuckDuckGo 免费可用）
WEB_SEARCH_ENGINE=auto
SERPER_API_KEY=your_serper_key       # 可选，Google 代理
BRAVE_SEARCH_API_KEY=your_brave_key # 可选，隐私搜索

# Agent 增强（默认配置即可，按需调整）
AGENT_USE_REFLECTION=true
AGENT_USE_DAG_EXECUTOR=false         # 实验性功能，默认关闭
AGENT_USE_KNOWLEDGE_GAP_DETECTION=true
AGENT_TOOL_QUALITY_TRACKING=true
```

### 6.3 开发配置

```bash
# .env 文件
USE_MOCK=true
APP_ENV=development
WEB_SEARCH_ENGINE=duckduckgo        # 仅用免费引擎，避免配额消耗
AGENT_USE_DAG_EXECUTOR=true          # 开发环境启用 DAG 测试
```

---

## 七、性能与安全

### 7.1 速率限制

| 服务 | 限制 | 缓解 |
|---|---|---|
| NCBI（无 Key） | 3 req/s | 令牌桶 + 7 天缓存 |
| NCBI（有 Key） | 10 req/s | 令牌桶 + 7 天缓存 |
| DuckDuckGo | 1 req/s | 24 小时缓存 |
| Serper | 2500 次/月 | 24 小时缓存 + 配额监控 |
| Brave | 2000 次/月 | 24 小时缓存 + 配额监控 |

### 7.2 超时控制

| 操作 | 超时 | 配置项 |
|---|---|---|
| NCBI 请求 | 30s | `NCBI_TIMEOUT_SEC` |
| 网络搜索 | 15s | `WEB_SEARCH_TIMEOUT_SEC` |
| 网页抓取 | 15s | `WEB_FETCH_TIMEOUT_SEC` |
| DAG 单步 | 30s | 硬编码 |
| Agent 整体 | 由 `AGENT_TASK_TIMEOUT_SEC` 控制 | 现有配置 |

### 7.3 安全约束

- **API Key 安全**：所有 API Key 通过环境变量注入，不硬编码源码（符合现有约定）
- **DAG 并发上限**：同层最大并发 5，避免事件循环阻塞
- **反思重试上限**：默认 2 次（`AGENT_REFLECTION_MAX_RETRIES`），防止死循环
- **盲区检测降级**：检测 3 次后仍未解决 → 强制 Final Answer，避免无限循环
- **网页抓取大小限制**：响应体最大 1MB，正文截断到 `WEB_FETCH_MAX_CHARS`
- **权限控制**：所有新工具需 `RESEARCHER` 及以上角色（与 `search_literature` 一致）

### 7.4 缓存策略

| 缓存类型 | TTL | 存储 | 失效策略 |
|---|---|---|---|
| NCBI 数据 | 7 天 | `external_loci_cache` 表 | TTL 自动过期 |
| 网络搜索结果 | 24 小时 | 内存 | 进程重启失效 |
| 工具质量指标 | 7 天 | 内存 | TTL 自动过期 |
| 网页抓取结果 | 不缓存 | — | 每次实时抓取 |

---

## 八、故障排查

### 8.1 NCBI 调用失败

**症状**：`search_ncbi` 工具返回空结果或错误

**排查步骤**：

1. 检查 `USE_MOCK` 设置：开发环境应为 `true`
2. 检查网络连接：`curl https://eutils.ncbi.nlm.nih.gov/entrez/eutils/einfo.fcgi`
3. 检查 API Key：`echo $NCBI_API_KEY`
4. 查看日志：`grep "NCBI" logs/app.log`

### 8.2 网络搜索无结果

**症状**：`web_search` 返回空列表

**排查步骤**：

1. 检查引擎可用性：`python -c "from app.services.search.duckduckgo import DuckDuckGoEngine; e = DuckDuckGoEngine(); print(e.is_available)"`
2. 检查 API Key 配置：Serper/Brave 未配置 Key 时自动跳过
3. 检查网络连接：DuckDuckGo 需能访问外网

### 8.3 Agent 反思死循环

**症状**：Agent 反复调用同一工具失败

**排查步骤**：

1. 检查 `AGENT_REFLECTION_MAX_RETRIES`：应 ≤2
2. 检查 `AGENT_USE_REFLECTION`：可临时关闭排查
3. 查看审计日志：`grep "reflection" logs/audit.log`

### 8.4 DAG 执行竞态

**症状**：并行步骤结果不一致

**排查步骤**：

1. 检查 `AGENT_USE_DAG_EXECUTOR`：可临时关闭回退到串行 ReAct
2. 检查 `ToolContext` 是否为不可变对象（设计要求）
3. 检查进度推送是否用 `asyncio.Lock` 保护

---

## 九、相关文件索引

### 9.1 源码文件

| 文件 | 职责 |
|---|---|
| [backend/app/clients/base.py](file:///g:/软件开发/AI药物/backend/app/clients/base.py) | NcbiClient ABC |
| [backend/app/clients/real/ncbi_real.py](file:///g:/软件开发/AI药物/backend/app/clients/real/ncbi_real.py) | RealNcbiClient |
| [backend/app/clients/mock/ncbi_mock.py](file:///g:/软件开发/AI药物/backend/app/clients/mock/ncbi_mock.py) | MockNcbiClient |
| [backend/app/services/agent/reflection.py](file:///g:/软件开发/AI药物/backend/app/services/agent/reflection.py) | Reflector |
| [backend/app/services/agent/dag_executor.py](file:///g:/软件开发/AI药物/backend/app/services/agent/dag_executor.py) | DagExecutor |
| [backend/app/services/agent/tool_quality.py](file:///g:/软件开发/AI药物/backend/app/services/agent/tool_quality.py) | ToolQualityTracker |
| [backend/app/services/agent/knowledge_gap.py](file:///g:/软件开发/AI药物/backend/app/services/agent/knowledge_gap.py) | KnowledgeGapDetector |
| [backend/app/services/agent/engine.py](file:///g:/软件开发/AI药物/backend/app/services/agent/engine.py) | AgentEngine（集成所有增强组件） |
| [backend/app/services/agent/prompts.py](file:///g:/软件开发/AI药物/backend/app/services/agent/prompts.py) | REFLECTION_PROMPT + KNOWLEDGE_GAP_DETECTION_PROMPT |
| [backend/app/services/agent/tools/ncbi.py](file:///g:/软件开发/AI药物/backend/app/services/agent/tools/ncbi.py) | SearchNcbiTool |
| [backend/app/services/agent/tools/web_search.py](file:///g:/软件开发/AI药物/backend/app/services/agent/tools/web_search.py) | WebSearchTool + FetchWebPageTool |
| [backend/app/services/search/base.py](file:///g:/软件开发/AI药物/backend/app/services/search/base.py) | SearchEngine ABC + URL 归一化 |
| [backend/app/services/search/duckduckgo.py](file:///g:/软件开发/AI药物/backend/app/services/search/duckduckgo.py) | DuckDuckGoEngine |
| [backend/app/services/search/serper.py](file:///g:/软件开发/AI药物/backend/app/services/search/serper.py) | SerperEngine |
| [backend/app/services/search/brave.py](file:///g:/软件开发/AI药物/backend/app/services/search/brave.py) | BraveSearchEngine |
| [backend/app/services/search/aggregator.py](file:///g:/软件开发/AI药物/backend/app/services/search/aggregator.py) | MultiEngineAggregator |
| [backend/app/services/search/fetcher.py](file:///g:/软件开发/AI药物/backend/app/services/search/fetcher.py) | WebPageFetcher |

### 9.2 测试文件

| 文件 | 覆盖范围 |
|---|---|
| [backend/tests/test_ncbi_client.py](file:///g:/软件开发/AI药物/backend/tests/test_ncbi_client.py) | NCBI 客户端单元测试 |
| [backend/tests/services/test_search.py](file:///g:/软件开发/AI药物/backend/tests/services/test_search.py) | 搜索引擎单元测试 |
| [backend/tests/test_agent_reflection.py](file:///g:/软件开发/AI药物/backend/tests/test_agent_reflection.py) | Reflector 单元测试 |
| [backend/tests/test_agent_dag_executor.py](file:///g:/软件开发/AI药物/backend/tests/test_agent_dag_executor.py) | DagExecutor 单元测试 |
| [backend/tests/test_agent_tool_quality.py](file:///g:/软件开发/AI药物/backend/tests/test_agent_tool_quality.py) | ToolQualityTracker 单元测试 |
| [backend/tests/test_agent_knowledge_gap.py](file:///g:/软件开发/AI药物/backend/tests/test_agent_knowledge_gap.py) | KnowledgeGapDetector 单元测试 |
| [backend/tests/test_agent_enhancements_integration.py](file:///g:/软件开发/AI药物/backend/tests/test_agent_enhancements_integration.py) | Agent 增强集成测试 |

### 9.3 配置文件

| 文件 | 修改内容 |
|---|---|
| [backend/app/core/config.py](file:///g:/软件开发/AI药物/backend/app/core/config.py) | 追加 NCBI/Web Search/Agent 增强配置段 |
| [backend/app/core/deps.py](file:///g:/软件开发/AI药物/backend/app/core/deps.py) | 追加 `get_ncbi_client()` 工厂 |
| [backend/requirements.txt](file:///g:/软件开发/AI药物/backend/requirements.txt) | 追加 `duckduckgo-search`/`trafilatura`/`pypdf` 依赖 |
