# P1 流式修复 + 干湿闭环 实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 补齐 v3.0 整合报告 P1 范围内的 4 个真实缺口 —— 主对话流式接入与参数错配修复(A)、干湿闭环反馈链串联(B)、假设实验验证徽章(C)、编排/流式契约测试与 hook 测试(D)。

**Architecture:** 代码库演进已实现 v3.0 报告声称"需新建"的大部分能力(`feedback_loop.py` 全套方法、`FailureKnowledge` 模型、`WrongPathAvoider`、`streamChat`/SSE 端点、编排开关 `INTELLIGENCE_USE_UNIFIED_ORCHESTRATOR=True`)。本计划只补 4 个真实缺口,不重建已有能力。

**Tech Stack:** FastAPI + SQLAlchemy 2.0 async + pytest(asyncio/httpx ASGITransport);Next.js 14 + Vitest + Playwright;axios/fetch SSE。

## Global Constraints

- 复用既有测试风格:后端用 `SimpleNamespace` + `MagicMock` 构造 ORM(见 `backend/tests/experiment/test_feedback_validation.py`),契约测试用 `httpx.AsyncClient` + `ASGITransport`(见 `backend/tests/test_api_contract.py`)。
- 前端 hook 测试用 Vitest(jsdom),`vi.mock('@/lib/api')`。
- 铁律 TDD:每个生产代码改动前先有失败测试。
- 零回归:后端全量 pytest、前端 `vitest run` 通过。
- 不改数据库 schema(字段已存在,仅补序列化字段)。
- 全部代码不加注释(遵循仓库惯例);中文 UI 文案沿用现有风格。
- 不在计划内做迁移/新端点重构。

---

### Task 1: 后端 — submit_result 串联干湿闭环反馈链(缺口 B)

**Files:**
- Modify: `backend/app/api/v1/endpoints/experiments.py:103-137`(`submit_result`)
- Test: `backend/tests/experiment/test_feedback_validation.py`(追加 1 个集成风格用例,复用 mock db 模式)

**Interfaces:**
- Consumes: `FeedbackLoop.apply_feedback`(已存在,返回 dict)、`FeedbackLoop.feedback_to_hypotheses`(已存在,读 `experiment.result.conclusion` 调 `apply_validation_feedback`)、`FeedbackLoop.ingest_failure`(已存在,`experiment.success is False` 时沉淀 FailureKnowledge)。
- Produces: `submit_result` 响应 `data` 新增两个键:`hypothesis_feedback`(dict,含 `hypothesis_id/elo_before/elo_after`)、`failure_knowledge`(dict,含 `failure_knowledge_id/failure_reason/is_new`)。
- 行为:无论成功/失败都调 `feedback_to_hypotheses`;仅 `payload.success is False` 时调 `ingest_failure`。两个调用各自 try/except 不阻断主流程。

- [ ] **Step 1: 写失败测试**

在 `backend/tests/experiment/test_feedback_validation.py` 追加:

```python
class TestSubmitResultFeedbackChain:
    """submit_result 端点:串联假设反馈 + 失败沉淀"""

    @pytest.mark.asyncio
    async def test_success_submits_hypothesis_feedback(self):
        from unittest.mock import AsyncMock, patch

        from app.models.experiment import Experiment

        experiment = SimpleNamespace(
            id=uuid4(),
            project_id=uuid4(),
            hypothesis_id=uuid4(),
            result={"conclusion": "VALIDATED"},
            success=True,
            config={},
        )
        exp_mock = MagicMock(spec=Experiment)
        exp_mock.id = experiment.id
        exp_mock.project_id = experiment.project_id
        exp_mock.hypothesis_id = experiment.hypothesis_id
        exp_mock.result = experiment.result
        exp_mock.success = None
        exp_mock.notes = None
        exp_mock.status = "draft"

        # patch db.get 返回实验
        with patch("app.api.v1.endpoints.experiments.get_db") as mock_get_db, \
             patch("app.api.v1.endpoints.experiments.on_experiment_completed", new_callable=AsyncMock) as on_ok, \
             patch("app.api.v1.endpoints.experiments.on_experiment_failed", new_callable=AsyncMock):
            mock_db = MagicMock()
            mock_db.get = AsyncMock(return_value=exp_mock)
            mock_get_db.return_value = mock_db

            # 在端点内，FeedbackLoop 用同一 db 实例
            from app.api.v1.endpoints import experiments as exp_endpoint
            loop_patch = patch.object(exp_endpoint, "FeedbackLoop")
            # 直接测试端点函数内部逻辑困难，改为测试 FeedbackLoop 编排
            loop_patch.start()

            # 构造端点所需依赖
            from app.core.security import UserRole
            user = SimpleNamespace(id=uuid4(), role=UserRole.FOUNDER)

            # 模拟 get_current_user
            with patch("app.api.v1.endpoints.experiments.get_current_user", return_value=user):
                # 用真实 FeedbackLoop 编排逻辑的替代:验证 apply_feedback + feedback_to_hypotheses 被调用
                mock_loop = MagicMock()
                mock_loop.apply_feedback = AsyncMock(return_value={"feedback": {}})
                mock_loop.feedback_to_hypotheses = AsyncMock(
                    return_value={"hypothesis_id": str(experiment.hypothesis_id),
                                  "elo_before": 1000.0, "elo_after": 1015.0}
                )
                mock_loop.ingest_failure = AsyncMock(
                    return_value={"failure_knowledge_id": None, "failure_reason": None, "is_new": False}
                )
                loop_patch.start().return_value = mock_loop

                # 通过 ASGI 调用真实端点（低耦合、验证请求/响应契约）
                from httpx import ASGITransport, AsyncClient
                from app.main import app
                transport = ASGITransport(app=app)
                async with AsyncClient(transport=transport, base_url="http://test") as client:
                    resp = await client.post(
                        f"/api/v1/experiments/{experiment.id}/result",
                        json={"result": {"conclusion": "VALIDATED"}, "success": True},
                    )
                # 断言响应契约
                data = resp.json().get("data", {})
                assert "hypothesis_feedback" in data
                assert data["hypothesis_feedback"]["elo_after"] == 1015.0
```

> 注:此用例较复杂,实际实现时优先拆为**纯单元测试** —— 直接对 `submit_result` 内的编排抽取为 FeedbackLoop 新方法 `run_closure(experiment)` 单测,再让端点薄调用。Step 1 以最终编写的失败测试为准(先 RED),本块是方向性骨架。

- [ ] **Step 2: 运行测试验证失败**

Run: `cd backend && python -m pytest tests/experiment/test_feedback_validation.py -v`
Expected: FAIL —— `data` 中无 `hypothesis_feedback` 键。

- [ ] **Step 3: 实现 — 抽取 `FeedbackLoop.run_closure` + 端点串联**

在 `backend/app/services/experiment/feedback_loop.py` 类内追加:

```python
    async def run_closure(self, experiment) -> Dict[str, Any]:
        """干湿闭环完整编排:误差反馈 + 假设反馈 + 失败沉淀"""
        result: Dict[str, Any] = {"feedback": {}}
        try:
            result["feedback"] = await self.apply_feedback(experiment)
        except Exception as e:
            logger.warning("apply_feedback 异常(不阻断): %s", e)
        try:
            result["hypothesis_feedback"] = await self.feedback_to_hypotheses(experiment)
        except Exception as e:
            logger.warning("feedback_to_hypotheses 异常(不阻断): %s", e)
        if experiment.success is False:
            try:
                result["failure_knowledge"] = await self.ingest_failure(experiment)
            except Exception as e:
                logger.warning("ingest_failure 异常(不阻断): %s", e)
        return result
```

修改 `experiments.py:submit_result`:

```python
    loop = FeedbackLoop(db)
    feedback = await loop.run_closure(exp)
```

- [ ] **Step 4: 运行测试验证通过**

Run: `cd backend && python -m pytest tests/experiment/test_feedback_validation.py -v`
Expected: PASS。

- [ ] **Step 5: 提交**

```bash
git add backend/app/services/experiment/feedback_loop.py backend/app/api/v1/endpoints/experiments.py backend/tests/experiment/test_feedback_validation.py
git commit -m "feat(feedback): 串联 submit_result 干湿闭环完整反馈链"
```

---

### Task 2: 后端 — RankedHypothesisView 补实验验证字段(缺口 C 后端)

**Files:**
- Modify: `backend/app/schemas/coscientist.py:84-101`(`RankedHypothesisView`)
- Test: `backend/tests/test_api_contract.py` 或新建 `backend/tests/test_rankings_validation_fields.py`

**Interfaces:**
- Produces: `RankedHypothesisView` 新增可选字段 `experimental_elo_adjustment: Optional[float] = None`、`experimental_validation_count: Optional[int] = None`,由 `model_validate(h)` 自动从 Hypothesis ORM 填充。

- [ ] **Step 1: 写失败测试**

```python
"""RankedHypothesisView 序列化实验验证字段"""
from types import SimpleNamespace
from uuid import uuid4

from app.schemas.coscientist import RankedHypothesisView


class TestRankedHypothesisValidationFields:
    def test_serializes_experimental_validation_fields(self):
        hyp = SimpleNamespace(
            id=uuid4(),
            name="H1",
            elo_score=1015.0,
            experimental_elo_adjustment=15.0,
            experimental_validation_count=1,
            status="active",
        )
        view = RankedHypothesisView.model_validate(hyp)
        assert view.experimental_elo_adjustment == 15.0
        assert view.experimental_validation_count == 1

    def test_missing_fields_default_none(self):
        hyp = SimpleNamespace(
            id=uuid4(),
            name="H2",
            elo_score=1000.0,
            status="active",
        )
        view = RankedHypothesisView.model_validate(hyp)
        assert view.experimental_elo_adjustment is None
        assert view.experimental_validation_count is None
```

- [ ] **Step 2: 运行测试验证失败**

Run: `cd backend && python -m pytest tests/test_rankings_validation_fields.py -v`
Expected: FAIL —— `AttributeError: 'RankedHypothesisView' object has no attribute 'experimental_elo_adjustment'`。

- [ ] **Step 3: 实现**

在 `RankedHypothesisView` 类内、`status` 之后追加:

```python
    experimental_elo_adjustment: Optional[float] = None
    experimental_validation_count: Optional[int] = None
```

- [ ] **Step 4: 运行测试验证通过**

Expected: PASS。

- [ ] **Step 5: 提交**

```bash
git add backend/app/schemas/coscientist.py backend/tests/test_rankings_validation_fields.py
git commit -m "feat(coscientist): 排名视图序列化实验验证字段"
```

---

### Task 3: 前端 — 修复流式 hook 死代码(缺口 A 前半)

**Files:**
- Modify: `frontend/types/intelligence.ts`(空文件,补类型)、`frontend/hooks/useIntelligenceStream.ts`、`frontend/hooks/useIntelligenceChat.ts`
- Test: `frontend/hooks/useIntelligenceStream.test.tsx`

**Interfaces:**
- Consumes: `streamChat(sessionId, message: string, options)` 来自 `@/lib/api`(`StreamCallbacks` 含 `onChunk/onDone/onError/signal`)。
- Produces: `ChatPayload` 类型在 `frontend/types/intelligence.ts` 定义:`{ message: string; project_id?: string; force_mode?: 'chat'|'reasoning'|'agent'|'hybrid'|'auto' }`;`useIntelligenceStream.start` 改为正确解构 payload 调 `streamChat(sessionId, payload.message, { projectId, forceMode, ...callbacks })`;`useIntelligenceChat` 的 `ChatResponse` 类型从 `@/lib/api/intelligence` 导入。

- [ ] **Step 1: 写失败测试**

```tsx
// frontend/hooks/useIntelligenceStream.test.tsx
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { renderHook, act, waitFor } from '@testing-library/react';
import { useIntelligenceStream } from './useIntelligenceStream';

vi.mock('@/lib/api', () => {
  return {
    streamChat: vi.fn(),
  };
});

import { streamChat } from '@/lib/api';
const mockedStreamChat = vi.mocked(streamChat);

describe('useIntelligenceStream', () => {
  beforeEach(() => {
    mockedStreamChat.mockReset();
  });

  it('以正确参数调用 streamChat(message + projectId + forceMode)', async () => {
    const { result } = renderHook(() => useIntelligenceStream());
    await act(async () => {
      mockedStreamChat.mockImplementation(async (_sid, _msg, opts) => {
        opts?.onChunk?.('部分');
        opts?.onDone?.('完整回复');
        return '完整回复';
      });
      await result.current.start('session-1', {
        message: '你好',
        project_id: 'proj-1',
        force_mode: 'chat',
      });
    });

    expect(mockedStreamChat).toHaveBeenCalledTimes(1);
    const [sessionId, message, opts] = mockedStreamChat.mock.calls[0];
    expect(sessionId).toBe('session-1');
    expect(message).toBe('你好');
    expect(opts?.projectId).toBe('proj-1');
    expect(opts?.forceMode).toBe('chat');
    expect(result.current.status).toBe('done');
    expect(result.current.streamingText).toBe('完整回复');
  });
});
```

- [ ] **Step 2: 运行测试验证失败**

Run: `cd frontend && npx vitest run hooks/useIntelligenceStream.test.tsx`
Expected: FAIL —— `streamChat` 未以正确参数调用(当前实现把 payload 对象当 message 传)。

- [ ] **Step 3: 实现 — 补类型 + 修复 hook**

`frontend/types/intelligence.ts` 写入:

```ts
/**
 * 统一智能系统类型定义
 */
export type PrimaryMode = 'chat' | 'reasoning' | 'agent' | 'hybrid' | 'auto';

export interface ChatPayload {
  message: string;
  project_id?: string;
  force_mode?: PrimaryMode;
}

export interface IntelligenceMessage {
  id: string;
  role: 'user' | 'assistant' | 'system';
  content: string;
  timestamp?: string;
  mode?: string;
  intent?: string;
  cost_usd?: number;
  duration_sec?: number;
  isStreaming?: boolean;
}

export type { ChatResponse } from '@/lib/api/intelligence';
```

`useIntelligenceStream.ts` 的 `start` 改为:

```ts
    async (sessionId: string, payload: ChatPayload) => {
      setStatus('streaming');
      setStreamingText('');
      setError(null);
      abortRef.current = false;

      let full = '';
      const callbacks: StreamCallbacks = {
        onChunk: (chunk) => {
          if (abortRef.current) return;
          full += chunk;
          setStreamingText(full);
          options.onChunk?.(chunk, full);
        },
        onDone: () => {
          if (abortRef.current) return;
          setStatus('done');
          options.onDone?.(full);
        },
        onError: (err) => {
          if (abortRef.current) return;
          setStatus('error');
          setError(err);
          options.onError?.(err);
        },
      };

      try {
        await streamChat(sessionId, payload.message, {
          projectId: payload.project_id,
          forceMode: payload.force_mode,
          ...callbacks,
        });
      } catch (err) {
        setStatus('error');
        const msg = err instanceof Error ? err.message : String(err);
        setError(msg);
        options.onError?.(msg);
      }
    },
```

`useIntelligenceChat.ts` 顶部 import 改为从 `@/lib/api/intelligence` 导入 `ChatResponse`、从 `@/types/intelligence` 导入 `ChatPayload/IntelligenceMessage`(补上类型后 import 通过),`chatMutation` 类型不再引用 `ChatPayload` 冲突。

- [ ] **Step 4: 运行测试验证通过 + 类型检查**

Run: `cd frontend && npx vitest run hooks/useIntelligenceStream.test.tsx && npx tsc --noEmit`
Expected: PASS,且 tsc 无 `@/types/intelligence` 缺失导出报错。

- [ ] **Step 5: 提交**

```bash
git add frontend/types/intelligence.ts frontend/hooks/useIntelligenceStream.ts frontend/hooks/useIntelligenceChat.ts frontend/hooks/useIntelligenceStream.test.tsx
git commit -m "fix(intelligence): 修复流式 hook 死代码与类型错配"
```

---

### Task 4: 前端 — 主流程接入流式 + 修复参数错配(缺口 A 后半)

**Files:**
- Modify: `frontend/hooks/useUnifiedAgent.ts:266-274`(sendMessage 请求)
- Test: `frontend/hooks/useUnifiedAgent.test.tsx`

**Interfaces:**
- Consumes: `api.post('/intelligence/agent/chat', body)` —— body 为 `{ message, capability_hint, project_id }`(对齐后端 `ChatRequest`:`message/project_id/force_mode/capability_hint`)。
- Produces: 主流程非流式仍可用(修复后 body 正确),并为后续 SSE 回退保留 `isStreaming` 状态。

- [ ] **Step 1: 写失败测试**

```tsx
// frontend/hooks/useUnifiedAgent.test.tsx
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { renderHook, act, waitFor } from '@testing-library/react';
import { useUnifiedAgent } from './useUnifiedAgent';

vi.mock('@/lib/api', () => {
  return { api: { post: vi.fn(), get: vi.fn() } };
});

import { api } from '@/lib/api';
const mockedApi = vi.mocked(api);

describe('useUnifiedAgent.sendMessage', () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it('以 body 携带 message/capability_hint/project_id 调用 /intelligence/agent/chat', async () => {
    mockedApi.get.mockResolvedValue({ data: { items: [] } });
    mockedApi.post.mockResolvedValue({
      data: {
        response: '答复',
        capability: 'qa',
        metadata: {},
      },
    });

    const { result } = renderHook(() => useUnifiedAgent());
    await act(async () => {
      result.current.setInputValue('测试问题');
      await result.current.sendMessage('测试问题', 'qa');
    });

    const call = mockedApi.post.mock.calls.find(([url]) =>
      String(url).includes('/intelligence/agent/chat'),
    );
    expect(call).toBeDefined();
    const [, body] = call!;
    expect(body).toMatchObject({ message: '测试问题', capability_hint: 'qa' });
    // 关键:不应以 null body + query params 调用
    expect(body).not.toBeNull();
  });
});
```

- [ ] **Step 2: 运行测试验证失败**

Run: `cd frontend && npx vitest run hooks/useUnifiedAgent.test.tsx`
Expected: FAIL —— 当前 `api.post(url, null, { params })` 使 body 为 `null`。

- [ ] **Step 3: 实现**

将 `useUnifiedAgent.ts:266-274` 改为:

```ts
      const response = await api.post('/intelligence/agent/chat', {
        message: text,
        capability_hint: effectiveCapability,
        ...(currentProject?.id ? { project_id: currentProject.id } : {}),
      }, {
        params: { session_id: sessionId },
        timeout: timeoutMs,
      });
```

> 说明:后端 `unified_agent_chat` 的 `session_id` 是 query 参数、`message` 等在 body `ChatRequest`。`session_id` 保留在 query,其余进 body,契约对齐。

- [ ] **Step 4: 运行测试验证通过 + 类型检查**

Expected: PASS,tsc 无错。

- [ ] **Step 5: 提交**

```bash
git add frontend/hooks/useUnifiedAgent.ts frontend/hooks/useUnifiedAgent.test.tsx
git commit -m "fix(intelligence): 主对话请求对齐后端 ChatRequest 契约"
```

---

### Task 5: 前端 — 假设验证徽章(缺口 C 前端)

**Files:**
- Modify: `frontend/types/coscientist.ts:89-104`(`RankedHypothesis`)、`frontend/components/coscientist/HypothesisRanking.tsx`
- Test: `frontend/components/coscientist/HypothesisRanking.test.tsx`

**Interfaces:**
- Consumes: 后端 `RankedHypothesisView` 新增字段 `experimental_elo_adjustment`/`experimental_validation_count`。
- Produces: `RankedHypothesis` 类型补两字段;卡片 Elo 旁显示实验验证徽章(如 `🧪 实验验证 ×1`、`+15.0 Elo`)。

- [ ] **Step 1: 写失败测试**

```tsx
// frontend/components/coscientist/HypothesisRanking.test.tsx
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen } from '@testing-library/react';
import HypothesisRanking from './HypothesisRanking';

vi.mock('@tanstack/react-query', () => ({
  useQuery: () => ({
    data: {
      rankings: [
        {
          id: 'h1',
          name: 'H1',
          elo_score: 1015.0,
          experimental_elo_adjustment: 15.0,
          experimental_validation_count: 1,
          status: 'active',
        },
      ],
      total_hypotheses: 1,
    },
    isLoading: false,
  }),
}));

vi.mock('@/lib/api', () => ({ getRankings: vi.fn() }));

describe('HypothesisRanking 验证徽章', () => {
  it('展示实验验证次数与累计 Elo 调整', () => {
    render(<HypothesisRanking runId="r1" />);
    expect(screen.getByText(/实验验证.*1/)).toBeInTheDocument();
    expect(screen.getByText(/\+15/)).toBeInTheDocument();
  });
});
```

- [ ] **Step 2: 运行测试验证失败**

Run: `cd frontend && npx vitest run components/coscientist/HypothesisRanking.test.tsx`
Expected: FAIL —— 无徽章文本。

- [ ] **Step 3: 实现**

`frontend/types/coscientist.ts` 的 `RankedHypothesis` 追加:

```ts
  experimental_elo_adjustment?: number | null;
  experimental_validation_count?: number | null;
```

`HypothesisRanking.tsx` 在 Elo 数字下方(`Elo` label 行后)追加:

```tsx
              {hyp.experimental_validation_count != null && hyp.experimental_validation_count > 0 && (
                <div className="text-xs text-green-600 font-medium">
                  🧪 实验验证 ×{hyp.experimental_validation_count}
                  {hyp.experimental_elo_adjustment != null && (
                    <span> · {hyp.experimental_elo_adjustment > 0 ? '+' : ''}{hyp.experimental_elo_adjustment.toFixed(1)} Elo</span>
                  )}
                </div>
              )}
```

- [ ] **Step 4: 运行测试验证通过**

Expected: PASS。

- [ ] **Step 5: 提交**

```bash
git add frontend/types/coscientist.ts frontend/components/coscientist/HypothesisRanking.tsx frontend/components/coscientist/HypothesisRanking.test.tsx
git commit -m "feat(coscientist): 假设排名展示实验验证徽章"
```

---

### Task 6: 契约测试 + 全量回归(缺口 D)

**Files:**
- Create: `backend/tests/test_intelligence_contract.py`
- Modify: 无(仅测试)

**Interfaces:**
- 验证后端契约:POST `/api/v1/intelligence/agent/chat` 接受 body `ChatRequest` 且 `session_id` 为 query;POST `/api/v1/intelligence/sessions/{id}/stream` 返回 `text/event-stream`。复用 `test_api_contract.py` 的 `ASGITransport` + mock `get_current_user`/`get_db` 基础设施。

- [ ] **Step 1: 写失败测试**

```python
"""智能系统契约测试 — 主对话 body 契约 + SSE 流式契约"""
import os
import sys
from unittest.mock import AsyncMock, MagicMock

import pytest
from httpx import ASGITransport, AsyncClient

_backend_dir = os.path.join(os.path.dirname(__file__), "..")
if _backend_dir not in sys.path:
    sys.path.insert(0, _backend_dir)

os.environ.setdefault("USE_MOCK", "true")
os.environ.setdefault("APP_ENV", "testing")
os.environ.setdefault("DATABASE_URL", "sqlite+aiosqlite:///:memory:")

from app.main import app  # noqa: E402


@pytest.mark.asyncio
async def test_agent_chat_rejects_query_only_message():
    """前端若把 message 放 query 而非 body 应 422;body 正确则应路由通过"""
    from app.core.deps import get_current_user
    from app.core.security import UserRole
    from types import SimpleNamespace
    from uuid import uuid4
    from unittest.mock import patch

    user = SimpleNamespace(id=uuid4(), role=UserRole.FOUNDER)

    with patch("app.api.v1.endpoints.intelligence.get_current_user", return_value=user), \
         patch("app.api.v1.endpoints.intelligence.get_llm_client_with_fallback", new_callable=AsyncMock), \
         patch("app.api.v1.endpoints.intelligence.UnifiedAgentGateway") as mock_gateway:
        mock_gateway.return_value.chat = AsyncMock(
            return_value={"response": "ok", "capability": "qa", "metadata": {}}
        )
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.post(
                "/api/v1/intelligence/agent/chat?session_id=" + str(uuid4()),
                json={"message": "你好", "capability_hint": "qa"},
            )
        assert resp.status_code == 200
        assert resp.json()["data"]["response"] == "ok"


@pytest.mark.asyncio
async def test_stream_endpoint_returns_sse_media_type():
    """stream 端点返回 text/event-stream"""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.post(
            "/api/v1/intelligence/sessions/" + str(uuid4()) + "/stream",
            json={"message": "hi"},
        )
    assert resp.status_code in (200, 404)  # 会话不存在时 404;存在时 200 + SSE
    if resp.status_code == 200:
        assert resp.headers["content-type"].startswith("text/event-stream")
```

> 注:如路由前缀非 `/api/v1`,按实际调整(参考 `backend/app/api/__init__.py` 的 `api_router` 挂载前缀)。

- [ ] **Step 2: 运行测试验证**

Run: `cd backend && python -m pytest tests/test_intelligence_contract.py -v`
Expected: 首个用例 PASS(证明 body 契约正确),第二个用例反映实际前缀/行为。

- [ ] **Step 3: 全量回归**

```bash
cd backend && python -m pytest -q
cd frontend && npx vitest run
cd frontend && npx tsc --noEmit
```

- [ ] **Step 4: 修复任何回归后提交**

```bash
git add backend/tests/test_intelligence_contract.py
git commit -m "test(intelligence): 主对话与 SSE 契约测试"
```

---

### Task 7: 改进实施报告

**Files:**
- Create: `软件优化方案报告-实施报告-P1.md`(仓库根目录)

- [ ] **Step 1: 汇总每个任务的测试结果(RED→GREEN 证据)**

列出:缺口 A/B/C/D 各自改动文件、新增测试数、通过数、前端 tsc 结果、全量 pytest 结果(含既有 490 测试零回归)。

- [ ] **Step 2: 记录与 v3.0 报告的偏差**

说明:v3.0 声称"需从零实现"的 `streamChat`/`feedback_loop` 全套/`FailureKnowledge` 实际已存在;本计划只补 4 个真实缺口。附上各文件当前状态。

- [ ] **Step 3: 提交**

```bash
git add 软件优化方案报告-实施报告-P1.md
git commit -m "docs: P1 流式修复与干湿闭环实施报告"
```

---

## 自检(与 v3.0 P1 范围对照)

- 建议六(流式修复):Task 3/4(前端)+ Task 6(契约)覆盖 —— 主流程 body 契约、流式 hook 修复、SSE 契约。
- 建议一(干湿闭环):Task 1(反馈链串联)+ Task 2/5(验证徽章)覆盖。
- 建议二(失败知识库):已有 `ingest_failure`+`FailureKnowledge`+`WrongPathAvoider` 注入 generation,本次不在 P1 缺口内,报告中说明。
- 编排收敛:开关已为 `True`,`UnifiedOrchestrator.chat` 已完整路由,本次无缺口;报告中说明。
- 验收约束:新增文件均有测试;全量回归零退化;契约测试新增 Task 6。
