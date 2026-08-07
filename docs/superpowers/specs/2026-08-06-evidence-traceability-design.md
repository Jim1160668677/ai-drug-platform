# 证据溯源 UI — 设计文档

> Date: 2026-08-06
> Author: user + assistant
> Status: APPROVED

## Background

P2 建议四缺口。推理过程中学术检索步骤(tool_call)的结果缺乏可追溯性 — 用户无法看到检索到了哪些论文、论文来源,也无法调整检索策略重新执行。现有 `TraceTimeline` 只展示步骤元信息(step_type/cost/duration),不展示证据内容。

本 spec 聚焦两件事:**证据可点击溯源** + **用户干预重新执行**。

## In scope

1. **数据模型扩展** — `TraceStep` 增加 `evidence` 字段;后端 `ReasoningTrace` 的 `input_data`/`output_data` 按约定格式存储证据
2. **TraceTimeline 证据展开** — tool_call 步骤可展开,显示检索词/命中数/论文卡片(标题/作者/DOI/来源/链接)
3. **用户干预** — 调整检索词 / 添加数据源,通过新建 ReasoningTrace step 实现(原 step 不可变)
4. **重新执行端点** — `POST /api/v1/knowledge/academic-search/reexecute`

## Out of scope

- ScientistCopilot 浮窗的 StepTraceCard(独立 spec)
- 前端档位选择 UI(独立 spec)
- 全文 PDF 获取(仅元数据 + 摘要)
- WebSocket 实时推送(保持轮询)

## Design

### 1. 数据模型

**后端 ReasoningTrace** — 复用已有 `input_data`/`output_data`(JSON 字段),tool_call 步骤按约定填充:

```python
# 创建 tool_call step 时:
input_data = {"query": "EGFR cancer", "sources": ["pubmed", "biorxiv"], "limit": 10}
output_data = {
    "total_hits": {"pubmed": 5, "biorxiv": 3},
    "papers": [
        {
            "title": "EGFR抑制剂在NSCLC中的耐药机制",
            "authors": ["Smith J", "Lee K"],
            "doi": "10.1038/s41586-024-12345",
            "source": "pubmed",
            "url": "https://pubmed.ncbi.nlm.nih.gov/12345678",
            "relevance_score": 0.92,
            "abstract": "..."
        },
        # ...
    ]
}
```

**前端 TraceStep 类型扩展** — `frontend/lib/api/intelligence.ts`:

```typescript
export interface EvidencePaper {
  title: string;
  authors?: string[];
  doi?: string;
  source: string;
  url?: string;
  relevance_score?: number;
  abstract?: string;
}

export interface TraceStep {
  id: string;
  step_type: string;
  agent_name?: string | null;
  phase?: string | null;
  round_num?: number | null;
  decision_basis?: string | null;
  cost_usd?: number | null;
  duration_sec?: number | null;
  status: string;
  created_at?: string | null;
  evidence?: {
    query: string;
    sources: string[];
    total_hits: Record<string, number>;
    papers: EvidencePaper[];
  } | null;
}
```

**后端 API 序列化** — `getTrace` 端点返回时,从 `input_data`/`output_data` 中提取 evidence 并附加到 step:

```python
# 序列化逻辑(在 endpoint 层)
if step.step_type == "tool_call" and step.input_data and step.output_data:
    step_dict["evidence"] = {
        "query": step.input_data.get("query", ""),
        "sources": step.input_data.get("sources", []),
        "total_hits": step.output_data.get("total_hits", {}),
        "papers": step.output_data.get("papers", []),
    }
```

### 2. TraceTimeline 证据展开

修改 `frontend/components/intelligence/TraceTimeline.tsx`:

- **步骤渲染**:仅 `tool_call` + `evidence != null` 的步骤显示展开按钮(chevron 图标)
- **展开状态**:点击切换 `expandedSteps` Set,展开后显示证据卡片区
- **证据卡片区**:
  - 检索词摘要:`📎 证据: 检索 "EGFR cancer" (pubmed 5 + biorxiv 3)`
  - 论文卡片列表:每张卡片显示标题、作者(DOI)、来源徽章(彩色)、可点击链接
  - 底部操作按钮:`调整检索词`(✏️) / `添加数据源`(➕)
- **论文卡片点击**:新窗口打开 `url`(DOI/PubMed/biorxiv 链接)

### 3. 用户干预

两个干预共用一个模式:弹出交互 → 调用 API → 新 step 追加到 trace。

**调整检索词**:
- 点击 `调整检索词` → 弹出内联输入框(预填当前 query) → 用户修改 → 确认
- 调用 `reexecute` API(`query` 变更) → 返回新 step → 追加到时间线

**添加数据源**:
- 点击 `添加数据源` → 弹出 checkbox 列表(pubmed/biorxiv/arxiv/semantic_scholar/crossref) → 用户勾选额外源 → 确认
- 调用 `reexecute` API(`add_sources` 变更) → 返回新 step → 追加到时间线

**状态管理**:
- 展开/折叠状态:`Set<string>` (step IDs)
- 干预弹窗状态:`{ type: 'edit_query' | 'add_sources', stepId: string } | null`
- 新 step 追加后自动展开

### 4. 重新执行端点

`POST /api/v1/knowledge/academic-search/reexecute`

```python
class ReexecuteRequest(BaseModel):
    parent_step_id: str
    query: Optional[str] = None          # 新检索词(不传则沿用原 query)
    add_sources: List[str] = []          # 额外数据源
    limit_per_source: int = Field(default=10, ge=1, le=50)

class ReexecuteResponse(BaseModel):
    step_id: str
    papers: List[EvidencePaper]
    total_hits: Dict[str, int]
    search_time_ms: int
```

逻辑:
1. 加载 `parent_step` → 提取原 `input_data`(query/sources)
2. 合并:新 query(或原 query) + 原 sources + add_sources
3. 调用 `AcademicSearchClient.search_all()` 获取结果
4. 新建 `tool_call` step(`parent_step_id = parent_step.id`)
5. 返回新 step + 结果

## Testing Plan

### 前端测试

`TraceTimeline.test.tsx` 追加:
- 渲染 tool_call 步骤 + evidence → 显示展开按钮
- 点击展开 → 显示论文卡片列表
- 论文卡片点击 → 链接正确(pubmed/doi URL)
- 点击"调整检索词" → 弹出输入框 → 输入新词 → 调用 reexecute API → 新 step 追加
- 点击"添加数据源" → 弹出 checkbox → 勾选 → 调用 reexecute → 新 step 追加
- 无 evidence 的 tool_call 步骤 → 不显示展开按钮

### 后端测试

`test_academic_search_endpoint.py` 追加:
- `test_reexecute_change_query`:修改检索词 → 200 + 新 step 创建 + parent_step_id 正确
- `test_reexecute_add_sources`:添加数据源 → 200 + 结果包含新源
- `test_reexecute_invalid_parent`:不存在的 parent_step_id → 404
- `test_reexecute_preserves_original`:重新执行不修改原 step(input_data/output_data 不变)

### 契约测试

- `test_trace_step_includes_evidence`:tool_call 步骤的 trace 响应包含 evidence 字段
- `test_trace_step_evidence_null_for_non_tool`:非 tool_call 步骤 evidence 为 null

## Global Constraints

- 遵循现有组件模式(`@tanstack/react-query`,lucide-react 图标,Card 组件)
- 后端复用 `AcademicSearchClient`,不重复检索逻辑
- 原 ReasoningTrace step 不可变(重新执行只新建 step)
- 论文链接 `target="_blank" rel="noopener noreferrer"`
