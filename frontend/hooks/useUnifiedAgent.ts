'use client';

import { useState, useCallback, useEffect, useRef } from 'react';
import { api } from '@/lib/api';
import type { TierChoice } from '@/lib/api';

export type CapabilityType = 'qa' | 'reasoning' | 'agent' | 'auto';

export interface WorkflowStatus {
  step: string;
  brain: string;
  hands: Array<{ name: string; icon?: string }>;
  status: string;
}

export interface ReasoningTrace {
  id: string;
  step_type: string;
  agent_name?: string;
  phase?: string;
  round_num?: number;
  input_data?: Record<string, any>;
  output_data?: Record<string, any>;
  decision_basis?: string;
  cost_usd?: number;
  duration_sec?: number;
  status: string;
  created_at?: string;
  children?: ReasoningTrace[];
}

export interface UnifiedMessage {
  id: string;
  role: 'user' | 'assistant' | 'system';
  content: string;
  capability?: CapabilityType;
  timestamp?: string;
  metadata?: {
    elapsed_seconds?: number;
    routed_by?: string;
    references?: Array<{ title: string; url?: string }>;
    sources?: Array<{ text: string }>;
    run_id?: string;
    cost_usd?: number;
    tier?: string;
    tier_reason?: string;
  };
  suggestions?: SuggestionAction[];
  toolCalls?: Array<{
    tool: string;
    args?: Record<string, any>;
    thought?: string;
  }>;
  task_id?: string;
  status?: string;
  workflow_status?: WorkflowStatus;
}

export interface SuggestionAction {
  action: string;
  label: string;
  description: string;
  capability?: string;
  priority?: string;
}

export interface AgentSession {
  id: string;
  title: string;
  status: string;
  message_count: number;
  last_message_at?: string;
  created_at?: string;
  primary_mode?: string;
}

export interface CurrentProject {
  id: string;
  name: string;
}

export interface UnifiedAgentState {
  sessions: AgentSession[];
  currentSessionId: string | null;
  currentProject: CurrentProject | null;
  messages: UnifiedMessage[];
  isSending: boolean;
  inputValue: string;
  capability: CapabilityType;
  tier: TierChoice;
  availableCapabilities: Array<{
    type: string;
    name: string;
    description: string;
    latency_ms: number;
    cost_level: string;
  }>;
  suggestions: SuggestionAction[];
  error: string | null;
  isStreaming: boolean;
  workflowStatus: WorkflowStatus | null;
  reasoningTraces: ReasoningTrace[];
  currentRunId: string | null;
  isLoadingTraces: boolean;
  sendProgress: string | null;
}

export interface UnifiedAgentActions {
  setInputValue: (value: string) => void;
  sendMessage: (message?: string, capabilityHint?: CapabilityType, tierHint?: TierChoice) => Promise<void>;
  selectSession: (sessionId: string) => void;
  createNewSession: () => Promise<string>;
  setCapability: (capability: CapabilityType) => void;
  setTier: (tier: TierChoice) => void;
  clearError: () => void;
  applySuggestion: (suggestion: SuggestionAction) => void;
  loadCapabilities: () => Promise<void>;
  fetchReasoningTraces: (runId: string) => Promise<void>;
}

export type UnifiedAgent = UnifiedAgentState & UnifiedAgentActions;

const CAPABILITY_STORAGE_KEY = 'ai_drug_default_capability';

function buildReasoningDisplay(response: any): string {
  if (!response || typeof response !== 'object') return '';

  const parts: string[] = [];

  if (response.run_id) parts.push(`**运行ID**: ${response.run_id}`);
  if (response.total_rounds) parts.push(`\n**迭代轮数**: ${response.total_rounds}`);
  if (response.duration) parts.push(`**耗时**: ${response.duration.toFixed(1)}s`);
  if (response.total_cost) parts.push(`**成本**: $${response.total_cost.toFixed(4)}`);
  if (response.converged) parts.push(`**收敛**: 是`);

  if (response.final_rankings?.length) {
    parts.push('\n## 🏆 最终排名');
    response.final_rankings.forEach((h: any, i: number) => {
      parts.push(`\n### ${i + 1}. ${h.title || h.name || '假设'}`);
      if (h.content) parts.push(h.content.slice(0, 300));
      if (h.elo_score != null) parts.push(`- Elo 分数: ${h.elo_score.toFixed(1)}`);
      if (h.score != null) parts.push(`- 评分: ${h.score.toFixed(1)}`);
    });
  }

  if (response.meta_review) {
    parts.push('\n## 📋 元审查');
    if (response.meta_review.summary) parts.push(response.meta_review.summary.slice(0, 500));
  }

  if (response.error) {
    parts.push(`\n⚠️ **错误**: ${response.error}`);
  }

  return parts.join('\n');
}

export function useUnifiedAgent(initialSessionId?: string): UnifiedAgent {
  const [sessions, setSessions] = useState<AgentSession[]>([]);
  const [currentSessionId, setCurrentSessionId] = useState<string | null>(initialSessionId ?? null);
  const [currentProject, setCurrentProject] = useState<CurrentProject | null>(null);

  const [messages, setMessages] = useState<UnifiedMessage[]>([]);
  const [isSending, setIsSending] = useState(false);
  const [inputValue, setInputValue] = useState('');

  const [capability, setCapabilityState] = useState<CapabilityType>('auto');
  const [tier, setTierState] = useState<TierChoice>('auto');
  const setTier = useCallback((newTier: TierChoice) => {
    setTierState(newTier);
  }, []);

  const [availableCapabilities, setAvailableCapabilities] = useState<UnifiedAgentState['availableCapabilities']>([]);
  const [suggestions, setSuggestions] = useState<SuggestionAction[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [isStreaming, setIsStreaming] = useState(false);
  const [workflowStatus, setWorkflowStatus] = useState<WorkflowStatus | null>(null);
  const [reasoningTraces, setReasoningTraces] = useState<ReasoningTrace[]>([]);
  const [currentRunId, setCurrentRunId] = useState<string | null>(null);
  const [isLoadingTraces, setIsLoadingTraces] = useState(false);
  const [sendProgress, setSendProgress] = useState<string | null>(null);

  const messagesEndRef = useRef<HTMLDivElement>(null);

  const loadSessions = useCallback(async () => {
    try {
      const response = await api.get('/intelligence/sessions');
      const data = response.data;
      const items = data?.items || data || [];
      setSessions(items.map((s: any) => ({
        id: s.id,
        title: s.title || '新会话',
        status: s.status || 'active',
        message_count: s.message_count || 0,
        last_message_at: s.last_message_at,
        created_at: s.created_at,
        primary_mode: s.primary_mode,
      })));
    } catch (err) {
      console.error('Failed to load sessions:', err);
    }
  }, []);

  const loadSessionMessages = useCallback(async (sessionId: string) => {
    try {
      const response = await api.get(`/intelligence/sessions/${sessionId}`);
      const sessionData = response.data;
      if (sessionData?.context?.messages) {
        setMessages(sessionData.context.messages);
      } else {
        setMessages([]);
      }
    } catch (err) {
      console.error('Failed to load session messages:', err);
      setMessages([]);
    }
  }, []);

  const sendMessage = useCallback(async (message?: string, capabilityHint?: CapabilityType, tierHint?: TierChoice) => {
    const text = (message ?? inputValue).trim();
    if (!text || isSending) return;

    const effectiveCapability = capabilityHint || capability;
    const effectiveTier = tierHint || tier;

    const userMessage: UnifiedMessage = {
      id: `user-${Date.now()}`,
      role: 'user',
      content: text,
      capability: effectiveCapability,
      timestamp: new Date().toISOString(),
    };

    setMessages((prev) => [...prev, userMessage]);
    setInputValue('');
    setIsSending(true);
    setError(null);
    setSendProgress(effectiveCapability === 'reasoning' ? '正在启动科学推理引擎...' : effectiveCapability === 'agent' ? '正在调度 Agent 执行...' : '正在处理您的问题...');

    try {
      let sessionId = currentSessionId;

      if (!sessionId) {
        const session = await createNewSession();
        sessionId = session;
      }

      // 自适应超时：reasoning 模式根据问题复杂度动态调整
      // 简单问题 120s, 中等 300s, 复杂 600s
      let timeoutMs: number;
      if (effectiveCapability === 'reasoning') {
        const questionLen = text.length;
        const hasComplexKeywords = /机制|通路|网络|多组学|整合|系统|因果|调控/.test(text);
        const hasSimpleKeywords = /靶点|表达|筛选|找|查询|什么|哪个/.test(text);
        if (questionLen < 20 || hasSimpleKeywords) {
          timeoutMs = 120000; // 2min - fast
        } else if (hasComplexKeywords || questionLen > 80) {
          timeoutMs = 600000; // 10min - deep
        } else {
          timeoutMs = 300000; // 5min - standard
        }
        console.info(`[Agent] Reasoning timeout: ${timeoutMs / 1000}s (questionLen=${questionLen})`);
      } else if (effectiveCapability === 'agent') {
        timeoutMs = 180000;
      } else {
        timeoutMs = 60000;
      }

      if (effectiveCapability === 'reasoning') {
        setSendProgress('正在生成研究假设 (Generation)...');
        setTimeout(() => setSendProgress(prev => prev ? '正在进行假设辩论 (Debate)...' : null), 8000);
        setTimeout(() => setSendProgress(prev => prev ? '正在排名评估 (Ranking)...' : null), 20000);
        setTimeout(() => setSendProgress(prev => prev ? '正在综合审查 (Meta Review)...' : null), 35000);
      }

      const response = await api.post('/intelligence/agent/chat', {
        message: text,
        capability_hint: effectiveCapability,
        ...(currentProject?.id ? { project_id: currentProject.id } : {}),
        ...(effectiveTier && effectiveTier !== 'auto' ? { tier: effectiveTier } : {}),
      }, {
        params: { session_id: sessionId },
        timeout: timeoutMs,
      });

      const result = response.data;

      if (result) {
        const responseContent = result.response;
        const isReasoningResult = effectiveCapability === 'reasoning';
        const hasAnswer = responseContent && typeof responseContent === 'object' && 'answer' in responseContent;

        let displayContent: string;
        if (isReasoningResult && responseContent && typeof responseContent === 'object' && !hasAnswer) {
          displayContent = buildReasoningDisplay(responseContent);
        } else if (typeof responseContent === 'string') {
          displayContent = responseContent;
        } else if (responseContent && typeof responseContent === 'object' && hasAnswer) {
          displayContent = responseContent.answer || JSON.stringify(responseContent, null, 2);
        } else {
          displayContent = JSON.stringify(responseContent ?? result, null, 2);
        }

        const assistantMessage: UnifiedMessage = {
          id: `assistant-${Date.now()}`,
          role: 'assistant',
          content: displayContent,
          capability: result.capability,
          timestamp: new Date().toISOString(),
          metadata: {
            ...result.metadata,
            run_id: responseContent?.run_id,
            elapsed_seconds: result.metadata?.elapsed_seconds,
            cost_usd: responseContent?.total_cost || result.metadata?.cost_usd,
            tier: result.metadata?.tier,
            tier_reason: result.metadata?.tier_reason,
          },
          suggestions: result.suggestions,
          task_id: responseContent?.task_id,
          status: responseContent?.status,
          workflow_status: result.workflow_status,
        };

        setMessages((prev) => [...prev, assistantMessage]);

        if (result.workflow_status) {
          setWorkflowStatus(result.workflow_status);
        }

        if (result.suggestions) {
          setSuggestions(result.suggestions);
        }

        const runId = responseContent?.run_id || responseContent?.trace_id;
        if (runId) {
          setCurrentRunId(runId);
          await fetchReasoningTraces(runId);
        }
      }
    } catch (err: any) {
      console.error('Failed to send message:', err);
      const isTimeout = err.code === 'ECONNABORTED' || err.code === 'ERR_ABORTED' || err.message?.includes('timeout');
      const isNetworkError = err.code === 'ERR_NETWORK' || err.message?.includes('Network Error');
      const timeoutMinutes = Math.round(timeoutMs / 60000);
      let errorMsg: string;
      if (isTimeout) {
        if (effectiveCapability === 'reasoning') {
          errorMsg = `科学推理超时（超过${timeoutMinutes}分钟），系统已自动启用简化推理模式。建议：① 简化问题描述 ② 仅关注核心靶点/机制 ③ 使用 AI 问答模式快速获取初步答案`;
        } else if (err.code === 'ERR_ABORTED' && !err.message?.includes('timeout')) {
          errorMsg = '请求被中止（可能页面已导航或用户取消），请重试';
        } else {
          errorMsg = '请求超时，请重试或简化问题';
        }
      } else if (isNetworkError) {
        errorMsg = '无法连接后端服务，请确认后端已启动';
      } else {
        errorMsg = err.response?.data?.detail || err.response?.data?.message || err.message || '发送消息失败';
      }
      setError(errorMsg);

      setMessages((prev) => [...prev, {
        id: `error-${Date.now()}`,
        role: 'assistant',
        content: `❌ ${errorMsg}`,
        timestamp: new Date().toISOString(),
      }]);
    } finally {
      setIsSending(false);
      setSendProgress(null);
    }
  }, [inputValue, isSending, capability, tier, currentSessionId, currentProject]);

  const createNewSession = useCallback(async (): Promise<string> => {
    try {
      const response = await api.post('/intelligence/sessions', {
        title: '新会话',
        primary_mode: capability,
        ...(currentProject?.id ? { project_id: currentProject.id } : {}),
      });

      const sessionData = response.data;
      const newSessionId = sessionData?.id || '';

      if (newSessionId) {
        setCurrentSessionId(newSessionId);
        setMessages([]);
        setSuggestions([]);

        await loadSessions();
      }

      return newSessionId;
    } catch (err: any) {
      console.error('Failed to create session:', err);
      throw new Error(err.response?.data?.detail || '创建会话失败');
    }
  }, [capability, currentProject, loadSessions]);

  const selectSession = useCallback(async (sessionId: string) => {
    setCurrentSessionId(sessionId);
    setError(null);
    setWorkflowStatus(null);
    await loadSessionMessages(sessionId);
  }, [loadSessionMessages]);

  const setCapability = useCallback((newCapability: CapabilityType) => {
    setCapabilityState(newCapability);
    if (typeof window !== 'undefined') {
      localStorage.setItem(CAPABILITY_STORAGE_KEY, newCapability);
    }
  }, []);

  const clearError = useCallback(() => {
    setError(null);
  }, []);

  const applySuggestion = useCallback((suggestion: SuggestionAction) => {
    const suggestionPrompts: Record<string, string> = {
      deep_analysis: '请对刚才的问题进行深入科学分析',
      run_pipeline: '请运行一键药物发现流水线',
      search_literature: '请搜索相关科学文献',
      generate_hypothesis: '请基于当前分析生成科学假设',
      run_validation: '请设计验证实验方案',
      find_targets: '请查找相关药物靶点',
      view_results: '请显示当前任务的执行结果',
      refine_query: '请帮我优化查询参数',
      save_session: '请保存当前工作进展',
    };

    const message = suggestionPrompts[suggestion.action] || suggestion.description;
    setInputValue(message);
  }, []);

  const loadCapabilities = useCallback(async () => {
    try {
      const response = await api.get('/intelligence/agent/capabilities');
      const data = response.data;
      if (data?.capabilities) {
        setAvailableCapabilities(data.capabilities);
      }
    } catch (err) {
      console.error('Failed to load capabilities:', err);
      setAvailableCapabilities([
        { type: 'qa', name: 'AI问答', description: '快速回答问题', latency_ms: 2000, cost_level: 'low' },
        { type: 'reasoning', name: '科学推理', description: '深度科学分析', latency_ms: 10000, cost_level: 'medium' },
        { type: 'agent', name: 'Agent工作台', description: '执行复杂任务', latency_ms: 30000, cost_level: 'high' },
      ]);
    }
  }, []);

  useEffect(() => {
    const stored = localStorage.getItem(CAPABILITY_STORAGE_KEY) as CapabilityType | null;
    if (stored && stored !== 'auto') {
      setCapabilityState(stored);
    }
  }, []);

  useEffect(() => {
    loadSessions();
    loadCapabilities();
  }, [loadSessions, loadCapabilities]);

  useEffect(() => {
    if (currentSessionId) {
      loadSessionMessages(currentSessionId);
    }
  }, [currentSessionId, loadSessionMessages]);

  const fetchReasoningTraces = useCallback(async (runId: string) => {
    if (!runId) return;
    setIsLoadingTraces(true);
    try {
      const response = await api.get(`/intelligence/reasoning/runs/${runId}/traces`, {
        timeout: 15000,
      });
      const data = response.data;
      if (data?.tree?.roots && Array.isArray(data.tree.roots)) {
        setReasoningTraces(data.tree.roots);
      } else {
        setReasoningTraces([]);
      }
    } catch (err: any) {
      console.warn('Failed to load reasoning traces:', err?.message || err);
      setReasoningTraces([]);
    } finally {
      setIsLoadingTraces(false);
    }
  }, []);

  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [messages]);

  return {
    sessions,
    currentSessionId,
    currentProject,
    messages,
    isSending,
    inputValue,
    capability,
    tier,
    setTier,
    availableCapabilities,
    suggestions,
    error,
    isStreaming,
    workflowStatus,
    reasoningTraces,
    currentRunId,
    isLoadingTraces,
    sendProgress,
    messagesEndRef,
    setInputValue,
    sendMessage,
    selectSession,
    createNewSession,
    setCapability,
    clearError,
    applySuggestion,
    loadCapabilities,
    fetchReasoningTraces,
  };
}