# 前端档位选择 UI — 设计文档

> Date: 2026-08-07
> Author: user + assistant
> Status: APPROVED

## Background

P2 建议五缺口。后端三档推理(turbo/standard/deep)已完整实现:`config.py LLM_TIERS`、`IntentRouter.suggest_tier()`/`budget_aware_tier()` 自动推荐、`UnifiedOrchestrator.chat()` 已接收 `tier` 参数并返回 `{tier, tier_config, cost_usd}`。但 API 层未暴露 tier:ChatRequest 无 tier 字段、端点未透传、ChatResponse 不返回 tier;前端工作台无档位选择 UI。

本 spec 聚焦:**智能推荐 + 手动覆盖** 的档位选择 UI,打通 前端 → API → 编排器 → 成本显示 全链路。

## In scope

1. **后端 API 扩展** — ChatRequest 增加 `tier` 字段、端点透传、ChatResponse 返回 `tier`
2. **智能推荐端点** — `POST /intelligence/sessions/{id}/suggest-tier`,输入消息返回推荐档位(不执行推理)
3. **前端 TierBar 组件** — 输入框上方档位条,默认 auto(显示智能推荐),可展开三档手动覆盖
4. **成本预估显示** — 前端常量表(每档预估成本/耗时),对话气泡下方显示后端真实 cost_usd

## Out of scope

- 后端三档算法本身(已实现并有 32 例测试)
- 会话级档位持久化(仅 session 内 useState)
- ScientistCopilot 浮窗的档位入口(独立 spec)
- 预算额度管理 UI(仅展示成本)

## Design

### 1. 后端 API 扩展(最小改动)

**`backend/app/schemas/intelligence.py`**:

```python
class ChatRequest(BaseModel):
    """统一对话请求"""
    message: str = Field(..., min_length=1, max_length=10000, description="用户信息")
    project_id: Optional[UUID] = Field(None, description="项目 ID(可跨会话)")
    force_mode: Optional[str] = Field(None, description="强制模式: chat/reasoning/agent/hybrid")
    capability_hint: Optional[str] = Field(None, description="能力提示: qa/reasoning/agent/auto(仅 Agent 使用)")
    tier: Optional[str] = Field(None, description="档位: turbo/standard/deep,None 或 auto 时智能推荐")
```

```python
class ChatResponse(BaseSchema):
    """统一对话响应"""
    answer: str = Field("", description="文本回复")
    mode: str = Field("chat", description="实际路由模式")
    intent: Optional[Dict[str, Any]] = None
    session_id: str
    tier: str = Field("standard", description="实际使用的档位")
    tier_reason: Optional[str] = Field(None, description="档位选择原因(智能推荐时)")  # noqa: E501
    cost_usd: float = 0.0
    duration_sec: float = 0.0
```

**端点** `backend/app/api/v1/endpoints/intelligence.py`:
- `POST /intelligence/sessions/{session_id}/chat`:增加 `tier=body.tier` 透传给 `orchestrator.chat()`;非法 tier 由 orchestrator 既有 `_resolve_tier` 回退 auto(既有行为,不报错)
- `POST /intelligence/sessions/{session_id}/suggest-tier`(新增):body `{message}` → 调用 `IntentRouter.suggest_tier(message, ...)`,返回 `{tier, reason, confidence, tier_config}`;空消息 400

### 2. 智能推荐端点

```python
class TierSuggestRequest(BaseModel):
    message: str = Field(..., min_length=1, max_length=10000)

class TierSuggestResponse(BaseSchema):
    tier: str  # turbo/standard/deep
    reason: str = ""
    confidence: float = 0.0
    tier_config: Dict[str, Any] = Field(default_factory=dict)
```

调用链:端点 → `IntentRouter.suggest_tier(message, intent_mode=..., intent_confidence=...)`(使用规则引擎静态估算复杂度,无 LLM 调用,成本可忽略)。前端 debounce 300ms 在用户输入时调用。

### 3. 前端 TierBar 组件

**新文件** `frontend/components/intelligence/TierBar.tsx`:

```typescript
export type TierChoice = 'auto' | 'turbo' | 'standard' | 'deep';

interface TierBarProps {
  value: TierChoice;
  onValueChange: (tier: TierChoice) => void;
  recommended?: string | null;   // 来自 suggest-tier 端点
  recommendedReason?: string | null;
  disabled?: boolean;            // isSending 时禁用
}
```

- **auto 态**:显示 `⚡ 已智能选档: standard · 约 $0.01`(有 recommended 时用其值;无则占位 `智能选档中…`)
- **点击展开**:三档 segmented 切换(turbo/standard/deep),每档 label 下显示预估成本/耗时
- **手动态**:badge 显示 `手动: deep`,旁边出现 `恢复智能选档` 小链接
- 成本预估来自前端常量表(与 LLM_TIERS 对齐,仅展示用,不做权威计算):

```typescript
const TIER_META: Record<string, { label: string; desc: string; cost_hint: string; latency_hint: string }> = {
  turbo:    { label: 'turbo',    desc: '快筛',   cost_hint: '约 $0.005', latency_hint: '~60s' },
  standard: { label: 'standard', desc: '标准',   cost_hint: '约 $0.01',  latency_hint: '~5min' },
  deep:     { label: 'deep',     desc: '深度',   cost_hint: '约 $0.03',  latency_hint: '~10min' },
};
```

### 4. 数据流

1. 用户输入 → debounce 300ms 调 `suggestTier(sessionId, message)` → 显示推荐档位
2. 用户点发送 → `sendChat/streamChat` 携带 `tier`(auto 时省略或传 "auto")
3. 后端 orchestrator `_resolve_tier` 解析(force_tier 校验 + auto 推荐) → 执行 → 返回 `tier`/`cost_usd`
4. 前端对话气泡下方显示 `deep · $0.0231 · 42.3s`(真实值)

### 5. 前端 API 扩展

`frontend/lib/api/intelligence.ts`:
- `sendChat`/`streamChat` 的 `options` 增加 `tier?: TierChoice`
- ChatRequest body 增加 `tier`(仅手动选择时传,auto 不传)
- 新增 `suggestTier(sessionId, message): Promise<TierSuggestResponse>`
- ChatResponse 增加 `tier` 字段

### 6. 接入点

`frontend/app/workbench/intelligence/page.tsx`:
- `useUnifiedAgent` 返回对象增加 `tier`/`setTier` state;`sendMessage` 携带 tier
- 输入框上方渲染 `<TierBar>`,`isSending` 时禁用

### 7. 测试计划

**后端**(`backend/tests/test_tier_routing.py` 追加):
- `TestChatEndpointTierPropagation`:chat 端点传 tier=deep → ChatResponse.tier == "deep";不传 → 智能推荐
- `TestSuggestTierEndpoint`:空消息 400;正常消息返回合法档位 + reason;非法 tier 回退 auto(既有行为)

**前端**(`frontend/app/workbench/intelligence/page.test.tsx` + TierBar 新测试):
- TierBar:auto 态显示智能推荐;点击展开三档;手动选择后显示 badge;恢复智能选档
- page:发送时携带选中 tier;响应后气泡显示 tier + cost

## Verification

- 后端:新增测试通过 + 全量 `pytest`(3729+2 基准)
- 前端:`vitest run` 全量(599+ 基准)+ `tsc --noEmit`
