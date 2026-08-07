# Plan: 前端档位选择 UI - TierSelector

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 实现智能推荐 + 手动覆盖的档位选择 UI，打通前端 TierBar → 后端 suggest-tier / chat 透传 → 响应 tier 展示全链路。

**Architecture:** 
1. 后端: ChatRequest/ChatResponse 加 tier 字段 + 新增 suggest-tier 端点 + gateway 透传 tier
2. 前端: TierBar 组件 + API 扩展 + useUnifiedAgent tier 状态 + page 接入
3. 测试: 后端提案端点测试 + 前端组件测试 + 集成测试

**Tech Stack:** Python/FastAPI, React/Next.js, Vitest, Pytest

## Global Constraints
- 后端全量测试基线: 3729 passed (test_tier_routing.py 32 passed 已在基线内)
- 前端全量测试基线: 62 files / 599 tests passed (page.test.tsx 6 tests)
- tier 字段仅手动选择时透传，auto/None 由后端智能推荐
- 禁止修改 LLM_TIERS 配置 (backend/app/core/config.py:187-210)
- 成本显示为前端常量表 (非权威计算)，后端返回的 cost_usd 显示真实值
- 所有新增代码遵循现有模式

---

### Task 1: 后端 ChatRequest/ChatResponse 增加 tier 字段

**Files:**
- Modify: `backend/app/schemas/intelligence.py` (lines 58-73)
- Test: `backend/tests/test_tier_routing.py`

**Interfaces:**
- Consumes: 无新增依赖
- Produces: `ChatRequest.tier: Optional[str]`, `ChatResponse.tier: str`, `ChatResponse.tier_reason: Optional[str]`

- [ ] **Step 1: 在 ChatRequest 增加 tier 字段**
  ```python
  # backend/app/schemas/intelligence.py ~line 61-63
  class ChatRequest(BaseModel):
      """统一对话请求"""
      message: str = Field(..., min_length=1, max_length=10000, description="用户信息")
      project_id: Optional[UUID] = Field(None, description="项目 ID(可跨会话)")
      force_mode: Optional[str] = Field(None, description="强制模式: chat/reasoning/agent/hybrid")
      capability_hint: Optional[str] = Field(None, description="能力提示: qa/reasoning/agent/auto(仅 Agent 使用)")
      tier: Optional[str] = Field(None, description="档位: turbo/standard/deep,None 或 auto 时智能推荐")
  ```

- [ ] **Step 2: 在 ChatResponse 增加 tier 字段**
  ```python
  # backend/app/schemas/intelligence.py ~line 66-73
  class ChatResponse(BaseSchema):
      """统一对话响应"""
      answer: str = Field("", description="文本回复")
      mode: str = Field("chat", description="实际路由模式")
      intent: Optional[Dict[str, Any]] = None
      session_id: str
      tier: str = Field("standard", description="实际使用的档位")
      tier_reason: Optional[str] = Field(None, description="档位选择原因")
      cost_usd: float = 0.0
      duration_sec: float = 0.0
  ```

- [ ] **Step 3: 验证 schema 无循环引用**
  ```bash
  cd G:\软件开发\AI药物\backend && python -c "from app.schemas.intelligence import ChatRequest, ChatResponse; print('OK')"
  ```
  Expected: `OK`

- [ ] **Step 4: 提交**
  ```bash
  git add backend/app/schemas/intelligence.py
  git commit -m "feat(schemas): ChatRequest/ChatResponse 增加 tier 字段"
  ```

---

### Task 2: 后端 chat 端点透传 tier

**Files:**
- Modify: `backend/app/api/v1/endpoints/intelligence.py`
- Modify: `backend/app/services/intelligence/unified_agent_gateway.py`
- Test: `backend/tests/test_tier_routing.py` (追加)

**Interfaces:**
- Consumes: `ChatRequest.tier`
- Produces: 响应包含 `tier` 和 `tier_reason` 字段

- [ ] **Step 1: POST /sessions/{session_id}/chat 透传 tier**
  ```python
  # backend/app/api/v1/endpoints/intelligence.py ~line 156-160
  result = await orchestrator.chat(
      session_id=session.id, message=body.message, user=user,
      project_id=str(body.project_id) if body.project_id else None,
      force_mode=body.force_mode,
      tier=body.tier,
  )
  ```

- [ ] **Step 2: POST /agent/chat 透传 tier 到 gateway**
  ```python
  # backend/app/api/v1/endpoints/intelligence.py ~line 610-617
  result = await gateway.chat(
      session_id=session.id,
      message=body.message,
      user=user,
      project_id=str(body.project_id) if body.project_id else None,
      capability_hint=body.capability_hint,
      force_mode=body.force_mode,
      tier=body.tier,
  )
  ```

- [ ] **Step 3: Gateway.chat 接受 tier 参数**
  ```python
  # backend/app/services/intelligence/unified_agent_gateway.py ~line 198-206
  async def chat(
      self,
      session_id: UUID,
      message: str,
      user: Any,
      project_id: Optional[str] = None,
      capability_hint: Optional[str] = None,
      force_mode: Optional[str] = None,
      tier: Optional[str] = None,  # 新增
  ) -> Dict[str, Any]:
  ```
  并在 `_chat_via_orchestrator` 调用时透传 tier

- [ ] **Step 4: _chat_via_orchestrator 透传 tier 到 orchestrator.chat**
  ```python
  # backend/app/services/intelligence/unified_agent_gateway.py ~line 313-319
  result = await orchestrator.chat(
      session_id=session_id,
      message=message,
      user=user,
      project_id=project_id,
      force_mode=effective_force,
      tier=tier,  # 新增
  )
  ```

- [ ] **Step 5: gateway result metadata 增加 tier**
  ```python
  # backend/app/services/intelligence/unified_agent_gateway.py ~line 334-341
  gateway_result = {
      # ... existing fields ...
      "metadata": {
          # ... existing fields ...
          "tier": result.get("tier", "standard"),
          "tier_reason": result.get("tier_reason", None),
      },
  }
  ```

- [ ] **Step 6: 运行现有测试验证无回归**
  ```bash
  cd G:\软件开发\AI药物\backend && python -m pytest tests/test_tier_routing.py -v
  ```
  Expected: `32 passed`

- [ ] **Step 7: 提交**
  ```bash
  git add backend/app/api/v1/endpoints/intelligence.py backend/app/services/intelligence/unified_agent_gateway.py
  git commit -m "feat(gateway): chat 端点透传 tier 到 orchestrator"
  ```

---

### Task 3: 新增 suggest-tier 端点

**Files:**
- Modify: `backend/app/schemas/intelligence.py`
- Modify: `backend/app/api/v1/endpoints/intelligence.py`
- Modify: `backend/app/services/intelligence/intent_router.py`
- Create: `backend/tests/test_suggest_tier.py`

**Interfaces:**
- Consumes: `TierSuggestRequest.message: str`
- Produces: `TierSuggestResponse{tier, reason, confidence, tier_config}`

- [ ] **Step 1: 增加 TierSuggestRequest/Response schema**
  ```python
  # backend/app/schemas/intelligence.py (在 ChatResponse 后新增)
  class TierSuggestRequest(BaseModel):
      message: str = Field(..., min_length=1, max_length=5000, description="用户消息")
  
  class TierSuggestResponse(BaseSchema):
      tier: str = Field(..., description="推荐档位 turbo/standard/deep")
      reason: str = Field("", description="推荐原因")
      confidence: float = Field(0.0, description="意图置信度 0-1")
      tier_config: Dict[str, Any] = Field(default_factory=dict, description="档位配置")
  ```

- [ ] **Step 2: IntentRouter 增加 suggest_tier_detail 方法**
  ```python
  # backend/app/services/intelligence/intent_router.py (新增在 suggest_tier 附近)
  def suggest_tier_detail(self, message: str, force_tier: Optional[str] = None) -> Dict[str, Any]:
      """零成本档位推荐 (仅 keyword 路由，无 LLM 调用)"""
      intent = self._keyword_route(message)
      tier = self.suggest_tier(message, intent.mode, intent.confidence, force_tier=force_tier)
      return {
          "tier": tier,
          "reason": intent.reason,
          "confidence": intent.confidence,
      }
  ```

- [ ] **Step 3: 新增 suggest-tier 端点**
  ```python
  # backend/app/api/v1/endpoints/intelligence.py (新增端点)
  @router.post("/sessions/{session_id}/suggest-tier", response_model=StandardResponse)
  async def suggest_tier(
      session_id: UUID,
      body: TierSuggestRequest,
      db: AsyncSession = Depends(get_db),
      user: User = Depends(get_current_user),
  ):
      """推荐档位 (零成本，仅 keyword 路由)"""
      _get_session_or_404(db, session_id, user)
      router = IntentRouter(db=db, llm_client=None)
      detail = router.suggest_tier_detail(body.message)
      tier = detail["tier"]
      tier_config = settings.LLM_TIERS.get(tier, settings.LLM_TIERS.get(settings.DEFAULT_LLM_TIER, {}))
      resp = TierSuggestResponse(
          tier=tier,
          reason=detail["reason"],
          confidence=detail["confidence"],
          tier_config=tier_config,
      )
      return StandardResponse(success=True, data=resp.model_dump(mode="json"))
  ```

- [ ] **Step 4: 新增测试文件**
  ```python
  # backend/tests/test_suggest_tier.py
  import pytest
  from app.schemas.intelligence import TierSuggestRequest, TierSuggestResponse
  
  def test_suggest_tier_schema_turbo():
      req = TierSuggestRequest(message="什么是 EGFR?")
      assert req.message == "什么是 EGFR?"
  
  def test_suggest_tier_schema_complex():
      req = TierSuggestRequest(message="请分析 EGFR 在 NSCLC 中的耐药机制并设计联合用药方案")
      assert len(req.message) > 20
  
  def test_tier_suggest_response_fields():
      resp = TierSuggestResponse(tier="turbo", reason="test", confidence=0.5, tier_config={})
      assert resp.tier == "turbo"
      assert resp.confidence == 0.5
  ```

- [ ] **Step 5: 运行新测试**
  ```bash
  cd G:\软件开发\AI药物\backend && python -m pytest tests/test_suggest_tier.py -v
  ```
  Expected: `3 passed`

- [ ] **Step 6: 提交**
  ```bash
  git add backend/app/schemas/intelligence.py backend/app/api/v1/endpoints/intelligence.py backend/app/services/intelligence/intent_router.py backend/tests/test_suggest_tier.py
  git commit -m "feat(api): 新增 suggest-tier 端点"
  ```

---

### Task 4: 前端 API 层扩展

**Files:**
- Modify: `frontend/lib/api/intelligence.ts`
- Test: `frontend/lib/api/intelligence.test.ts` (如有)

**Interfaces:**
- Consumes: 无
- Produces: `sendChat`/`streamChat` 支持 tier 参数，`suggestTier` 函数

- [ ] **Step 1: 增加 TierChoice 类型和 suggestTier API**
  ```typescript
  // frontend/lib/api/intelligence.ts
  export type TierChoice = 'auto' | 'turbo' | 'standard' | 'deep';
  
  export interface TierSuggestResponse {
    tier: string;
    reason: string;
    confidence: number;
    tier_config: Record<string, unknown>;
  }
  
  export const suggestTier = (
    sessionId: string,
    message: string,
  ): Promise<TierSuggestResponse> => {
    return api
      .post(`/intelligence/sessions/${sessionId}/suggest-tier`, { message })
      .then(unwrap<TierSuggestResponse>);
  };
  ```

- [ ] **Step 2: sendChat/streamChat 增加 tier 参数**
  ```typescript
  // sendChat 修改
  export const sendChat = (
    sessionId: string,
    message: string,
    options: { projectId?: string; forceMode?: PrimaryMode; tier?: TierChoice } = {}
  ): Promise<ChatResponse> => {
    const body: ChatRequest = { message };
    if (options.projectId) body.project_id = options.projectId;
    if (options.forceMode) body.force_mode = options.force_mode;
    if (options.tier && options.tier !== 'auto') body.tier = options.tier;
    return api
      .post(`/intelligence/sessions/${sessionId}/chat`, body)
      .then(unwrap<ChatResponse>);
  };
  
  // streamChat 类似修改
  ```

- [ ] **Step 3: ChatRequest 增加 tier 字段**
  ```typescript
  export interface ChatRequest {
    message: string;
    project_id?: string;
    force_mode?: PrimaryMode;
    tier?: TierChoice;
  }
  ```

- [ ] **Step 4: ChatResponse 增加 tier 字段**
  ```typescript
  export interface ChatResponse {
    answer: string;
    mode: string;
    tier?: string;
    tier_reason?: string;
    [key: string]: unknown;
  }
  ```

- [ ] **Step 5: 验证 TypeScript 编译**
  ```bash
  cd G:\软件开发\AI药物\frontend && npx tsc --noEmit
  ```
  Expected: 0 errors

- [ ] **Step 6: 提交**
  ```bash
  git add frontend/lib/api/intelligence.ts
  git commit -m "feat(api): 扩展 ChatRequest/ChatResponse 支持 tier"
  ```

---

### Task 5: 实现 TierBar 组件

**Files:**
- Create: `frontend/components/intelligence/TierBar.tsx`
- Create: `frontend/components/intelligence/TierBar.test.tsx`

**Interfaces:**
- Consumes: `TierChoice`, `TierSuggestResponse`
- Produces: React 组件，显示当前档位并可切换

- [ ] **Step 1: 创建 TierBar 组件**
  ```tsx
  // frontend/components/intelligence/TierBar.tsx
  'use client';
  
  import { useState } from 'react';
  import clsx from 'clsx';
  import { Zap, ChevronDown, ChevronUp } from 'lucide-react';
  import type { TierChoice } from '@/lib/api';
  
  export type { TierChoice } from '@/lib/api';
  
  interface TierBarProps {
    value: TierChoice;
    onValueChange: (tier: TierChoice) => void;
    recommended?: string | null;
    recommendedReason?: string | null;
    disabled?: boolean;
  }
  
  const TIER_META: Record<string, { label: string; desc: string; cost_hint: string; latency_hint: string }> = {
    turbo: { label: 'turbo', desc: '快筛', cost_hint: '约 $0.005', latency_hint: '~60s' },
    standard: { label: 'standard', desc: '标准', cost_hint: '约 $0.01', latency_hint: '~5min' },
    deep: { label: 'deep', desc: '深度', cost_hint: '约 $0.03', latency_hint: '~10min' },
  };
  
  export function TierBar({ value, onValueChange, recommended, recommendedReason, disabled }: TierBarProps) {
    const [expanded, setExpanded] = useState(false);
    const isAuto = value === 'auto';
    const displayTier = isAuto ? (recommended || 'standard') : value;
    const meta = TIER_META[displayTier] || TIER_META.standard;
    
    return (
      <div className="flex items-center gap-2 px-3 py-1.5 bg-gray-50 rounded-lg border border-gray-200 text-xs">
        <button
          onClick={() => !disabled && setExpanded(!expanded)}
          disabled={disabled}
          className="flex items-center gap-1.5 text-gray-600 hover:text-gray-800 disabled:opacity-50"
        >
          <Zap className={clsx('w-3.5 h-3.5', isAuto ? 'text-amber-500' : 'text-primary-500')} />
          <span>{isAuto ? '智能选档' : '手动'}: <strong>{displayTier}</strong></span>
          <span className="text-gray-400">{meta.cost_hint} · {meta.latency_hint}</span>
          {expanded ? <ChevronUp className="w-3 h-3" /> : <ChevronDown className="w-3 h-3" />}
        </button>
        
        {expanded && (
          <div className="flex items-center gap-1">
            {(['turbo', 'standard', 'deep'] as TierChoice[]).map((tier) => (
              <button
                key={tier}
                onClick={() => { onValueChange(tier); setExpanded(false); }}
                disabled={disabled}
                className={clsx(
                  'px-2 py-1 rounded text-xs font-medium transition-colors',
                  value === tier
                    ? 'bg-primary-500 text-white'
                    : 'bg-white text-gray-600 hover:bg-gray-100 border border-gray-200',
                  disabled && 'opacity-50 cursor-not-allowed',
                )}
              >
                {tier}
              </button>
            ))}
            {isAuto && (
              <button
                onClick={() => { onValueChange('standard'); setExpanded(false); }}
                disabled={disabled}
                className="ml-1 text-[10px] text-gray-400 hover:text-gray-600"
              >
                恢复智能
              </button>
            )}
          </div>
        )}
      </div>
    );
  }
  ```

- [ ] **Step 2: 创建 TierBar 测试**
  ```tsx
  // frontend/components/intelligence/TierBar.test.tsx
  import { render, screen, fireEvent } from '@testing-library/react';
  import { TierBar } from './TierBar';
  
  describe('TierBar', () => {
    it('shows auto state with recommended tier', () => {
      render(<TierBar value="auto" onValueChange={() => {}} recommended="standard" />);
      expect(screen.getByText(/智能选档.*standard/)).toBeInTheDocument();
    });
  
    it('shows manual tier', () => {
      render(<TierBar value="deep" onValueChange={() => {}} />);
      expect(screen.getByText(/手动.*deep/)).toBeInTheDocument();
    });
  
    it('expands on click', () => {
      render(<TierBar value="auto" onValueChange={() => {}} recommended="standard" />);
      fireEvent.click(screen.getByRole('button'));
      expect(screen.getByText('turbo')).toBeInTheDocument();
      expect(screen.getByText('deep')).toBeInTheDocument();
    });
  
    it('calls onValueChange when selecting tier', () => {
      const onChange = vi.fn();
      render(<TierBar value="auto" onValueChange={onChange} recommended="standard" />);
      fireEvent.click(screen.getByRole('button'));
      fireEvent.click(screen.getByText('deep'));
      expect(onChange).toHaveBeenCalledWith('deep');
    });
  });
  ```

- [ ] **Step 3: 运行组件测试**
  ```bash
  cd G:\软件开发\AI药物\frontend && npx vitest run components/intelligence/TierBar.test.tsx --no-cov
  ```
  Expected: `4 passed`

- [ ] **Step 4: 提交**
  ```bash
  git add frontend/components/intelligence/TierBar.tsx frontend/components/intelligence/TierBar.test.tsx
  git commit -m "feat(ui): 新增 TierBar 组件"
  ```

---

### Task 6: 集成 TierBar 到 useUnifiedAgent 和 page

**Files:**
- Modify: `frontend/hooks/useUnifiedAgent.ts`
- Modify: `frontend/app/workbench/intelligence/page.tsx`
- Modify: `frontend/app/workbench/intelligence/page.test.tsx`

**Interfaces:**
- Consumes: `TierBar`, `suggestTier`
- Produces: `useUnifiedAgent` 返回 tier 状态和传递到 API 调用

- [ ] **Step 1: useUnifiedAgent 增加 tier 状态**
  ```typescript
  // frontend/hooks/useUnifiedAgent.ts line ~104-114 (UnifiedAgentActions)
  export interface UnifiedAgentActions {
    setInputValue: (value: string) => void;
    sendMessage: (message?: string, capabilityHint?: CapabilityType, tier?: TierChoice) => Promise<void>;
    selectSession: (sessionId: string) => void;
    createNewSession: () => Promise<string>;
    setCapability: (capability: CapabilityType) => void;
    clearError: () => void;
    applySuggestion: (suggestion: SuggestionAction) => void;
    loadCapabilities: () => Promise<void>;
    fetchReasoningTraces: (runId: string) => Promise<void>;
  }
  
  // 状态增加
  const [tier, setTier] = useState<TierChoice>('auto');
  ```

- [ ] **Step 2: sendMessage 携带 tier 到 agent/chat**
  ```typescript
  // frontend/hooks/useUnifiedAgent.ts line ~266-273
  const response = await api.post('/intelligence/agent/chat', {
    message: text,
    capability_hint: effectiveCapability,
    ...(currentProject?.id ? { project_id: currentProject.id } : {}),
    ...(tier && tier !== 'auto' ? { tier } : {}),
  }, {
    params: { session_id: sessionId },
    timeout: timeoutMs,
  });
  ```

- [ ] **Step 3: 从响应中捕获 tier**
  ```typescript
  // frontend/hooks/useUnifiedAgent.ts line ~293-309 (assistantMessage)
  const assistantMessage: UnifiedMessage = {
    // ... existing fields ...
    metadata: {
      ...result.metadata,
      run_id: responseContent?.run_id,
      elapsed_seconds: result.metadata?.elapsed_seconds,
      cost_usd: responseContent?.total_cost || result.metadata?.cost_usd,
      tier: result.metadata?.tier,
      tier_reason: result.metadata?.tier_reason,
    },
  };
  ```

- [ ] **Step 4: page.tsx 接入 TierBar**
  ```tsx
  // frontend/app/workbench/intelligence/page.tsx
  // 增加 import
  import { TierBar } from '@/components/intelligence/TierBar';
  
  // state
  const [tier, setTier] = useState<TierChoice>('auto');
  const [recommendedTier, setRecommendedTier] = useState<string | null>(null);
  const [recommendedReason, setRecommendedReason] = useState<string | null>(null);
  
  // 输入时 debounce 调用 suggestTier
  const handleInputChange = useCallback((value: string) => {
    setInputValue(value);
    if (value.trim()) {
      const timer = setTimeout(async () => {
        try {
          const session = await createNewSessionSilent();
          const resp = await suggestTier(session, value);
          setRecommendedTier(resp.tier);
          setRecommendedReason(resp.reason);
        } catch { /* ignore */ }
      }, 300);
      return () => clearTimeout(timer);
    }
  }, [/* deps */]);
  ```

- [ ] **Step 5: 在输入框上方渲染 TierBar**
  ```tsx
  // frontend/app/workbench/intelligence/page.tsx line ~740 (textarea 上方)
  <div className="flex items-center justify-between mb-2">
    <TierBar
      value={tier}
      onValueChange={setTier}
      recommended={recommendedTier}
      recommendedReason={recommendedReason}
      disabled={isSending}
    />
    <span className="text-[10px] text-gray-400">
      {lastMessage?.metadata?.tier ? `已用 ${lastMessage.metadata.tier} · $${lastMessage.metadata.cost_usd?.toFixed(4)}` : ''}
    </span>
  </div>
  ```

- [ ] **Step 6: 更新 page.test.tsx**
  ```tsx
  // 新增测试用例
  it('renders TierBar component', () => {
    renderWithProviders(<IntelligencePage />);
    expect(screen.getByText(/智能选档/)).toBeInTheDocument();
  });
  ```

- [ ] **Step 7: 运行前端测试**
  ```bash
  cd G:\软件开发\AI药物\frontend && npx vitest run app/workbench/intelligence/page.test.tsx --no-cov
  ```
  Expected: 现有测试通过 + 新增测试通过

- [ ] **Step 8: 全量前端测试验证**
  ```bash
  cd G:\软件开发\AI药物\frontend && npx vitest run --no-cov
  ```
  Expected: `599+ tests passed` (基线 599, 新增 ~1-2)

- [ ] **Step 9: 全量后端测试验证**
  ```bash
  cd G:\软件开发\AI药物\backend && python -m pytest tests/ -x -q
  ```
  Expected: `3729+ passed` (基线 3729, 新增 ~3)

- [ ] **Step 10: TypeScript 编译检查**
  ```bash
  cd G:\软件开发\AI药物\frontend && npx tsc --noEmit
  ```
  Expected: 0 errors

- [ ] **Step 11: 提交**
  ```bash
  git add frontend/hooks/useUnifiedAgent.ts frontend/app/workbench/intelligence/page.tsx frontend/app/workbench/intelligence/page.test.tsx
  git commit -m "feat(ui): 集成 TierBar 到工作台"
  ```

---

### Task 7: 最终验证与报告

- [ ] **Step 1: 全量测试汇总**
  ```bash
  # 后端
  cd G:\软件开发\AI药物\backend && python -m pytest tests/ -q --tb=short
  # 前端  
  cd G:\软件开发\AI药物\frontend && npx vitest run --no-cov
  ```

- [ ] **Step 2: Git 状态检查**
  ```bash
  git log --oneline -10
  git status
  ```

- [ ] **Step 3: 更新实施报告**
  - 在 `软件优化方案报告-实施报告-P1.md` 增加 P2 建议五前端部分
  - 记录测试基线变化

- [ ] **Step 4: 提交报告**
  ```bash
  git add 软件优化方案报告-实施报告-P1.md
  git commit -m "docs: 更新 P2 建议五前端实施记录"
  ```
