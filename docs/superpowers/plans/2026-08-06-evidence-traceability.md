# Evidence Traceability UI — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 实现推理过程证据溯源(可展开论文卡片+来源链接)和用户干预能力(调整检索词/添加数据源重新执行)。

**Architecture:** 后端扩展 getTrace 端点序列化 evidence 字段 + 新增 reexecute 端点;前端 TraceTimeline 增加展开/折叠证据卡片区 + 干预弹窗。

**Tech Stack:** FastAPI + Pydantic + React + @tanstack/react-query + lucide-react

## Global Constraints

- 复用 AcademicSearchClient,不重复检索逻辑
- 原 ReasoningTrace step 不可变(重新执行只新建 step)
- 论文链接 target="_blank" rel="noopener noreferrer"
- 遵循现有组件模式(@tanstack/react-query, lucide-react, Card)
- 无 TBD/TODO,每步可独立测试

---

### Task 1: 后端 — evidence 序列化

**Files:**
- Modify: `backend/app/api/v1/endpoints/intelligence.py`(getTrace 序列化逻辑)
- Test: `backend/tests/test_evidence_trace.py`

**Interfaces:**
- Consumes: ReasoningTrace 模型(input_data/output_data)
- Produces: step_dict 附加 evidence 字段

- [ ] **Step 1: Write the failing test**

```python
import pytest
from httpx import ASGITransport, AsyncClient
from app.main import app

@pytest.mark.asyncio
async def test_trace_tool_call_includes_evidence(auth_headers):
    """tool_call 步骤应包含 evidence 字段"""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get("/intelligence/sessions/{session_id}/trace", headers=auth_headers)
    assert resp.status_code == 200
    traces = resp.json()["data"]["traces"]
    tool_steps = [t for t in traces if t["step_type"] == "tool_call"]
    for step in tool_steps:
        if step.get("evidence"):
            assert "query" in step["evidence"]
            assert "papers" in step["evidence"]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_evidence_trace.py -v --no-cov`
Expected: FAIL

- [ ] **Step 3: Implement evidence 序列化**

在 `getTrace` 端点序列化时,对 tool_call 步骤从 input_data/output_data 提取 evidence:

```python
# intelligence.py getTrace 序列化部分
if step.step_type == "tool_call" and step.input_data and step.output_data:
    step_dict["evidence"] = {
        "query": step.input_data.get("query", ""),
        "sources": step.input_data.get("sources", []),
        "total_hits": step.output_data.get("total_hits", {}),
        "papers": step.output_data.get("papers", []),
    }
else:
    step_dict["evidence"] = None
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_evidence_trace.py -v --no-cov`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add backend/app/api/v1/endpoints/intelligence.py tests/test_evidence_trace.py
git commit -m "feat: serialize evidence field in getTrace for tool_call steps"
```

---

### Task 2: 后端 — reexecute 端点

**Files:**
- Create: `backend/app/api/v1/endpoints/academic_search.py`(或在 knowledge.py 追加)
- Modify: `backend/app/api/v1/router.py`(注册路由)
- Test: `backend/tests/test_evidence_trace.py`(追加)

**Interfaces:**
- Consumes: AcademicSearchClient, ReasoningTrace 模型
- Produces: `POST /api/v1/knowledge/academic-search/reexecute`

- [ ] **Step 1: Write the failing test**

```python
@pytest.mark.asyncio
async def test_reexecute_change_query(auth_headers):
    """修改检索词重新执行"""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.post("/api/v1/knowledge/academic-search/reexecute",
                                json={"parent_step_id": "step-1", "query": "new query"},
                                headers=auth_headers)
    assert resp.status_code == 200
    data = resp.json()["data"]
    assert "step_id" in data
    assert "papers" in data
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_evidence_trace.py::test_reexecute_change_query -v --no-cov`
Expected: FAIL(route not found)

- [ ] **Step 3: Implement reexecute 端点**

```python
@router.post("/academic-search/reexecute", response_model=StandardResponse)
async def academic_search_reexecute(payload: ReexecuteRequest,
                                    current_user=Depends(get_current_user)):
    from app.services.analyzer.academic_search_client import AcademicSearchClient
    # 1. 加载 parent step
    parent = await db.get(ReasoningTrace, payload.parent_step_id)
    if not parent:
        raise NotFoundError("parent step not found")
    # 2. 提取原 query/sources
    orig_query = parent.input_data.get("query", "")
    orig_sources = parent.input_data.get("sources", [])
    new_query = payload.query or orig_query
    all_sources = list(set(orig_sources + payload.add_sources))
    # 3. 重新检索
    client = AcademicSearchClient()
    t0 = time.time()
    raw = await client.search_all(new_query, all_sources, payload.limit_per_source)
    papers = [p for plist in raw.values() for p in plist]
    papers = client.deduplicate(papers)
    papers = AcademicSearchClient.sort_by_relevance(papers)
    # 4. 新建 step
    new_step = ReasoningTrace(
        session_id=parent.session_id,
        step_type="tool_call",
        parent_step_id=parent.id,
        input_data={"query": new_query, "sources": all_sources},
        output_data={"total_hits": {s: len(l) for s, l in raw.items()},
                     "papers": [p.model_dump() for p in papers]},
    )
    db.add(new_step)
    await db.commit()
    return success_response(ReexecuteResponse(
        step_id=str(new_step.id), papers=papers,
        total_hits={s: len(l) for s, l in raw.items()},
        search_time_ms=int((time.time() - t0) * 1000),
    ).model_dump())
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_evidence_trace.py::test_reexecute_change_query -v --no-cov`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add backend/app/api/v1/endpoints/knowledge.py backend/tests/test_evidence_trace.py
git commit -m "feat: add academic-search/reexecute endpoint for evidence re-fetch"
```

---

### Task 3: 前端 — TraceStep 类型扩展

**Files:**
- Modify: `frontend/lib/api/intelligence.ts`(追加 EvidencePaper 接口)
- Test: 无需单独测试(类型变更)

**Interfaces:**
- Produces: EvidencePaper, TraceStep.evidence 字段

- [ ] **Step 1: 修改类型定义**

在 `frontend/lib/api/intelligence.ts` 中追加:

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

// TraceStep 接口追加:
export interface TraceStep {
  // ... existing fields ...
  evidence?: {
    query: string;
    sources: string[];
    total_hits: Record<string, number>;
    papers: EvidencePaper[];
  } | null;
}
```

- [ ] **Step 2: 运行 TypeScript 编译验证**

Run: `npx tsc --noEmit`
Expected: 0 errors

- [ ] **Step 3: Commit**

```bash
git add frontend/lib/api/intelligence.ts
git commit -m "feat: extend TraceStep type with evidence field"
```

---

### Task 4: 前端 — TraceTimeline 证据展开

**Files:**
- Modify: `frontend/components/intelligence/TraceTimeline.tsx`
- Test: `frontend/components/intelligence/TraceTimeline.test.tsx`(追加)

**Interfaces:**
- Consumes: Task 3 TraceStep.evidence
- Produces: 可展开证据卡片区

- [ ] **Step 1: Write the failing test**

```tsx
import { render, screen, fireEvent } from '@testing-library/react';
import TraceTimeline from './TraceTimeline';

it('展开 tool_call 证据步骤显示论文卡片', async () => {
  const step = {
    id: 's1', step_type: 'tool_call', status: 'completed',
    evidence: { query: 'EGFR', sources: ['pubmed'],
      total_hits: { pubmed: 1 },
      papers: [{ title: 'Test Paper', doi: '10.123', source: 'pubmed',
                 url: 'https://x.org/p1' }],
    },
  };
  // render with mock getTrace returning [step]
  fireEvent.click(screen.getByTestId('expand-s1'));
  expect(screen.getByText('Test Paper')).toBeInTheDocument();
  expect(screen.getByText('EGFR')).toBeInTheDocument();
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `npx vitest run TraceTimeline.test.tsx -t "展开" --no-cov`
Expected: FAIL

- [ ] **Step 3: Implement evidence expansion**

在 TraceTimeline.tsx:
1. 新增 `expandedSteps` state(`Set<string>`)
2. tool_call + evidence 步骤渲染展开按钮
3. 展开后渲染证据卡片区:检索词摘要 + 论文卡片列表
4. 论文卡片:标题/作者/DOI/来源徽章/链接

- [ ] **Step 4: Run test to verify it passes**

Run: `npx vitest run TraceTimeline.test.tsx --no-cov`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add frontend/components/intelligence/TraceTimeline.tsx
git frontend/components/intelligence/TraceTimeline.test.tsx
git commit -m "feat: TraceTimeline evidence expandable cards"
```

---

### Task 5: 前端 — 用户干预 UI

**Files:**
- Modify: `frontend/components/intelligence/TraceTimeline.tsx`(追加干预弹窗)
- Test: `frontend/components/intelligence/TraceTimeline.test.tsx`(追加)

**Interfaces:**
- Consumes: Task 2 reexecute API
- Produces: 调整检索词/添加数据源弹窗 + 新 step 追加

- [ ] **Step 1: Write the failing test**

```tsx
it('调整检索词后调用 reexecute API 并追加新 step', async () => {
  // render step with evidence
  fireEvent.click(screen.getByTestId('expand-s1'));
  fireEvent.click(screen.getByText('调整检索词'));
  // modal appears
  fireEvent.change(screen.getByTestId('query-input'), { target: { value: 'KRAS' } });
  fireEvent.click(screen.getByTestId('confirm-btn'));
  // wait for API call + new step rendered
  await waitFor(() => {
    expect(screen.getByText('KRAS')).toBeInTheDocument();
  });
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `npx vitest run TraceTimeline.test.tsx -t "调整检索词" --no-cov`
Expected: FAIL

- [ ] **Step 3: Implement intervention UI**

1. 干预弹窗 state + 渲染
2. `调整检索词`:内联输入框 + 确认 → reexecute mutation
3. `添加数据源`:checkbox 列表 + 确认 → reexecute mutation
4. 成功后追加新 step 到 traces 列表并自动展开

- [ ] **Step 4: Run test to verify it passes**

Run: `npx vitest run TraceTimeline.test.tsx --no-cov`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add frontend/components/intelligence/TraceTimeline.tsx
git commit -m "feat: user intervention UI for evidence re-fetch"
```

---

### Task 6: 集成验证

**Files:** none(verification only)

- [ ] **Step 1: Run full frontend test suite**

Run: `cd frontend && npx vitest run --no-cov`
Expected: All PASS

- [ ] **Step 2: Run full backend test suite**

Run: `cd backend && pytest tests/ --no-cov -q`
Expected: 0 failed

- [ ] **Step 3: 修复任何回归**

如果失败,定位原因并修复,提交修复 commit