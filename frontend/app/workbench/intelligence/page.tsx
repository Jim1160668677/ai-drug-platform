'use client';

import { useState, useRef, useCallback, useEffect } from 'react';
import { useSearchParams } from 'next/navigation';
import {
  X,
  PanelRight,
  Menu,
  Plus,
  Sparkles,
  Zap,
  Search,
  Clock,
  Layers,
  FileText,
  Target,
  Cpu,
  Loader2,
  CheckCircle2,
  AlertCircle,
  Send,
  ChevronRight,
  Bot,
  User,
  ListChecks,
  Brain,
  Hand,
} from 'lucide-react';
import clsx from 'clsx';
import { useResponsiveLayout } from '@/hooks/useMediaQuery';
import {
  useUnifiedAgent,
  type CapabilityType,
  type UnifiedMessage,
  type SuggestionAction,
} from '@/hooks/useUnifiedAgent';
import Card from '@/components/ui/Card';
import EmptyState from '@/components/ui/EmptyState';
import DagPhaseTimeline, { type DagNodeStatusEvent } from '@/components/agent/DagPhaseTimeline';
import StepTraceTimeline, { type StepTraceEvent } from '@/components/agent/StepTraceTimeline';

const CAPABILITY_META: Record<
  CapabilityType,
  { label: string; icon: typeof Sparkles; description: string }
> = {
  qa: { label: 'QA问答', icon: FileText, description: '基于知识库快速回答' },
  reasoning: { label: '科学推理', icon: Cpu, description: '深度科学分析与推理' },
  agent: { label: 'Agent执行', icon: Bot, description: '调用工具执行复杂任务' },
  auto: { label: '自动判断', icon: Sparkles, description: '由系统自动路由能力' },
};

const RIGHT_TABS = [
  { key: 'context', label: '上下文', icon: Layers },
  { key: 'dag',     label: '流程DAG', icon: Brain },
  { key: 'trace',   label: '追溯', icon: Clock },
  { key: 'evidence',label: '证据', icon: Search },
  { key: 'analysis',label: '分析', icon: FileText },
] as const;

type RightTabKey = (typeof RIGHT_TABS)[number]['key'];

export default function IntelligencePage() {
  const searchParams = useSearchParams();
  const initialSessionId = searchParams.get('session') ?? undefined;

  const { isDesktop, isTablet, isMobile } = useResponsiveLayout();

  const agent = useUnifiedAgent(initialSessionId);
  const {
    sessions,
    currentSessionId,
    messages,
    inputValue,
    capability,
    availableCapabilities,
    suggestions,
    error,
    isSending,
    currentProject,
    sendMessage,
    selectSession,
    createNewSession,
    setCapability,
    applySuggestion,
    setInputValue,
    clearError,
    workflowStatus,
  } = agent;

  const [activeTab, setActiveTab] = useState<RightTabKey>('context');
  const [sidebarOpen, setSidebarOpen] = useState(false);
  const [panelOpen, setPanelOpen] = useState(false);
  const [showCreateConfirm, setShowCreateConfirm] = useState(false);

  const [dagEvents, setDagEvents] = useState<DagNodeStatusEvent[]>([]);
  const [stepTraceEvents, setStepTraceEvents] = useState<StepTraceEvent[]>([]);
  const [latestCompression, setLatestCompression] = useState<null | {
    stage: string; before: number; after: number; saved: number; ratio: number;
    level?: string; budget_chars?: number;
  }>(null);

  const messagesEndRef = useRef<HTMLDivElement>(null);
  const capabilityRef = useRef<HTMLDivElement>(null);
  const [capabilityMenuOpen, setCapabilityMenuOpen] = useState(false);

  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [messages]);

  useEffect(() => {
    const onDocClick = (e: MouseEvent) => {
      if (
        capabilityMenuOpen &&
        capabilityRef.current &&
        !capabilityRef.current.contains(e.target as Node)
      ) {
        setCapabilityMenuOpen(false);
      }
    };
    document.addEventListener('mousedown', onDocClick);
    return () => document.removeEventListener('mousedown', onDocClick);
  }, [capabilityMenuOpen]);

  useEffect(() => {
    const collectedDag: DagNodeStatusEvent[] = [];
    const collectedStep: StepTraceEvent[] = [];
    let lastCompress: typeof latestCompression = null;

    for (const msg of messages) {
      const md = msg.metadata;
      if (!md) continue;

      if (Array.isArray((md as { dag_events?: DagNodeStatusEvent[] }).dag_events)) {
        for (const ev of (md as { dag_events: DagNodeStatusEvent[] }).dag_events) {
          if (ev && typeof ev.phase === 'string') {
            collectedDag.push({
              phase: ev.phase,
              round: typeof ev.round === 'number' ? ev.round : 0,
              status: (['pending', 'running', 'done', 'error'] as const).includes(ev.status as any)
                ? (ev.status as 'pending' | 'running' | 'done' | 'error')
                : 'pending',
              duration_ms: typeof ev.duration_ms === 'number' ? ev.duration_ms : 0,
              tokens: typeof ev.tokens === 'number' ? ev.tokens : 0,
              cost_usd: typeof ev.cost_usd === 'number' ? ev.cost_usd : 0,
              extra: ev.extra,
            });
          }
        }
      }

      if (Array.isArray((md as { step_trace_events?: StepTraceEvent[] }).step_trace_events)) {
        for (const ev of (md as { step_trace_events: StepTraceEvent[] }).step_trace_events) {
          if (ev && typeof ev.step === 'number') {
            collectedStep.push({
              step: ev.step,
              thought: ev.thought,
              action: ev.action,
              action_input: ev.action_input,
              observation: ev.observation,
              duration_ms: ev.duration_ms,
              tokens: ev.tokens,
              cost_usd: ev.cost_usd,
              status: (['running', 'done', 'error', 'skipped'] as const).includes(ev.status as any)
                ? (ev.status as 'running' | 'done' | 'error' | 'skipped')
                : undefined,
            });
          }
        }
      }

      const comp = (md as { compression_stats?: { stage?: string; before_chars?: number; after_chars?: number; ratio?: number; details?: { level?: string; budget_chars?: number } } }).compression_stats;
      if (comp && typeof comp === 'object') {
        const before = typeof comp.before_chars === 'number' ? comp.before_chars : 0;
        const after = typeof comp.after_chars === 'number' ? comp.after_chars : 0;
        const ratio = typeof comp.ratio === 'number' ? comp.ratio : (before > 0 ? after / before : 1);
        lastCompress = {
          stage: comp.stage ?? 'unknown',
          before,
          after,
          saved: Math.max(0, before - after),
          ratio,
          level: comp.details?.level,
          budget_chars: comp.details?.budget_chars,
        };
      }

      if (msg.toolCalls && msg.toolCalls.length > 0) {
        for (let i = 0; i < msg.toolCalls.length; i++) {
          const tc = msg.toolCalls[i];
          collectedStep.push({
            step: collectedStep.length + 1,
            thought: tc.thought,
            action: tc.tool,
            action_input: tc.args ?? null,
            status: 'done',
          });
        }
      }
    }

    setDagEvents(collectedDag);
    setStepTraceEvents(collectedStep);
    setLatestCompression(lastCompress);
  }, [messages]);

  const handleSelectSession = useCallback(
    async (id: string) => {
      await selectSession(id);
      setSidebarOpen(false);
    },
    [selectSession],
  );

  const handleCreateSession = useCallback(async () => {
    try {
      await createNewSession();
      setSidebarOpen(false);
      setShowCreateConfirm(false);
    } catch (e) {
      console.error(e);
    }
  }, [createNewSession]);

  const handleSend = useCallback(() => {
    sendMessage();
  }, [sendMessage]);

  const handleKeyDown = useCallback(
    (e: React.KeyboardEvent<HTMLTextAreaElement>) => {
      if (e.key === 'Enter' && !e.shiftKey) {
        e.preventDefault();
        handleSend();
      }
    },
    [handleSend],
  );

  const currentCapabilityInfo =
    availableCapabilities.find((c) => c.type === capability) ?? null;
  const capabilityMeta = CAPABILITY_META[capability];
  const CurrentCapIcon = capabilityMeta.icon;

  const renderMessageContent = (msg: UnifiedMessage) => {
    if (msg.toolCalls && msg.toolCalls.length > 0) {
      return (
        <div className="space-y-2">
          {msg.content && (
            <p className="whitespace-pre-wrap text-sm leading-relaxed">{msg.content}</p>
          )}
          <div className="rounded-md border border-gray-200 bg-gray-50/80 p-3 space-y-2">
            <div className="flex items-center gap-1.5 text-xs font-medium text-gray-600">
              <ListChecks className="w-3.5 h-3.5" />
              工具调用（{msg.toolCalls.length}）
            </div>
            {msg.toolCalls.map((tc, i) => (
              <div key={i} className="text-xs space-y-1">
                <div className="flex items-center gap-2">
                  <span className="font-mono font-medium text-primary-700">{tc.tool}</span>
                  {tc.thought && (
                    <span className="text-gray-500 truncate italic">— {tc.thought}</span>
                  )}
                </div>
                {tc.args && Object.keys(tc.args).length > 0 && (
                  <pre className="bg-white border border-gray-200 rounded px-2 py-1 text-[11px] text-gray-500 overflow-x-auto">
                    {JSON.stringify(tc.args, null, 2)}
                  </pre>
                )}
              </div>
            ))}
          </div>
        </div>
      );
    }

    if (msg.task_id || msg.status) {
      return (
        <div className="space-y-2">
          {msg.content && (
            <p className="whitespace-pre-wrap text-sm leading-relaxed">{msg.content}</p>
          )}
          <div className="flex items-center gap-1.5 rounded-md border border-blue-100 bg-blue-50 px-3 py-2 text-xs text-blue-700">
            <Loader2 className="w-3.5 h-3.5 animate-spin" />
            任务：{msg.task_id || '进行中'} · 状态：{msg.status || 'running'}
          </div>
        </div>
      );
    }

    if (msg.metadata?.sources && msg.metadata.sources.length > 0) {
      return (
        <div className="space-y-2">
          <p className="whitespace-pre-wrap text-sm leading-relaxed">{msg.content}</p>
          <div className="rounded-md border border-gray-200 bg-gray-50 p-2">
            <div className="text-[11px] font-medium text-gray-500 mb-1">引用来源</div>
            <ul className="space-y-0.5">
              {msg.metadata.sources.map((s, i) => (
                <li key={i} className="text-xs text-gray-600 line-clamp-2">
                  · {s.text}
                </li>
              ))}
            </ul>
          </div>
        </div>
      );
    }

    if (msg.workflow_status) {
      return (
        <div className="space-y-2">
          {msg.content && (
            <p className="whitespace-pre-wrap text-sm leading-relaxed">{msg.content}</p>
          )}
          <div className="rounded-md border border-indigo-100 bg-indigo-50/50 p-2.5 space-y-2">
            <div className="flex items-center gap-2 text-xs">
              <div className="flex items-center gap-1">
                <Brain className="w-3 h-3 text-indigo-600" />
                <span className="font-medium text-indigo-700" suppressHydrationWarning>{msg.workflow_status.brain}</span>
              </div>
              <ChevronRight className="w-3 h-3 text-gray-400" />
              <div className="flex items-center gap-1 flex-wrap">
                {msg.workflow_status.hands?.map((h, i) => (
                  <span key={i} className="inline-flex items-center gap-0.5 px-1.5 py-0.5 bg-white border border-gray-200 rounded text-[10px] text-gray-600">
                    <Hand className="w-2.5 h-2.5 text-green-600" />
                    {h.icon || '🔧'} {h.name}
                  </span>
                ))}
              </div>
              <span className={clsx(
                'ml-auto inline-flex items-center gap-0.5 px-1.5 py-0.5 rounded text-[10px]',
                msg.workflow_status.status === 'completed'
                  ? 'bg-green-100 text-green-700'
                  : 'bg-amber-100 text-amber-700'
              )}>
                <CheckCircle2 className="w-2.5 h-2.5" />
                {msg.workflow_status.status === 'completed' ? '已完成' : '运行中'}
              </span>
            </div>
          </div>
        </div>
      );
    }

    return <p className="whitespace-pre-wrap text-sm leading-relaxed">{msg.content}</p>;
  };

  const renderMessage = (msg: UnifiedMessage) => {
    const isUser = msg.role === 'user';
    const isSystem = msg.role === 'system';

    return (
      <div
        key={msg.id}
        className={clsx(
          'flex gap-2.5 py-3',
          isUser ? 'flex-row-reverse' : 'flex-row',
          isSystem && 'bg-amber-50/40 rounded-md',
        )}
      >
        <div
          className={clsx(
            'flex-shrink-0 w-7 h-7 rounded-full flex items-center justify-center text-white',
            isUser ? 'bg-primary-500' : 'bg-gray-600',
          )}
        >
          {isUser ? <User className="w-4 h-4" /> : <Bot className="w-4 h-4" />}
        </div>
        <div
          className={clsx(
            'flex-1 min-w-0 max-w-[85%] rounded-2xl px-3.5 py-2.5',
            isUser
              ? 'bg-primary-50 text-gray-800 rounded-tr-sm'
              : 'bg-white border border-gray-200 text-gray-800 rounded-tl-sm',
          )}
        >
          <div className="flex items-center gap-2 mb-1 text-[11px] text-gray-400">
            {msg.capability && (
              <span className="inline-flex items-center gap-0.5 px-1.5 py-0.5 rounded bg-gray-100 text-gray-600">
                {CAPABILITY_META[msg.capability]?.label || msg.capability}
              </span>
            )}
            {msg.metadata?.routed_by && (
              <span className="text-gray-400">路由：{msg.metadata.routed_by}</span>
            )}
            {msg.metadata?.elapsed_seconds != null && (
              <span className="text-gray-400">{msg.metadata.elapsed_seconds.toFixed(1)}s</span>
            )}
          </div>
          {renderMessageContent(msg)}
        </div>
      </div>
    );
  };

  const renderTabContent = () => {
    if (!currentSessionId) {
      return (
        <div className="h-full flex items-center justify-center">
          <EmptyState
            icon={Sparkles}
            title="选择会话后查看"
            description="右侧将显示会话的上下文、追溯、证据等信息"
          />
        </div>
      );
    }

    switch (activeTab) {
      case 'context':
        return (
          <div className="space-y-3">
            <div className="text-xs text-gray-500">
              会话 ID：{currentSessionId}
            </div>
            <div className="rounded-md border border-gray-200 bg-gray-50 p-3 text-xs space-y-1">
              <div className="font-medium text-gray-700 mb-1">会话概要</div>
              <div>消息数：{messages.length}</div>
              <div>当前能力：{capabilityMeta.label}</div>
              {currentProject && <div>项目：{currentProject.name}</div>}
            </div>
            <div className="rounded-md border border-gray-200 p-3 text-xs">
              <div className="font-medium text-gray-700 mb-2">最近能力路由</div>
              {messages
                .filter((m) => m.capability || m.metadata?.routed_by)
                .slice(-5)
                .map((m) => (
                  <div key={m.id} className="flex items-center gap-1.5 py-0.5">
                    <ChevronRight className="w-3 h-3 text-gray-400" />
                    <span className="text-gray-600">
                      {CAPABILITY_META[m.capability ?? 'auto']?.label || m.capability}
                    </span>
                    {m.metadata?.routed_by && (
                      <span className="text-gray-400 text-[10px]">
                        ({m.metadata.routed_by})
                      </span>
                    )}
                  </div>
                ))}
              {messages.filter((m) => m.capability).length === 0 && (
                <div className="text-gray-400">暂无能力路由记录</div>
              )}
            </div>
          </div>
        );
      case 'dag':
        return (
          <div className="space-y-3">
            <DagPhaseTimeline events={dagEvents} />
            <div className="rounded-md border border-gray-200 p-3 text-xs space-y-2">
              <div className="font-medium text-gray-700 flex items-center justify-between">
                <span>智能精简指标</span>
                {latestCompression && (
                  <span className="text-[10px] text-gray-400">
                    stage: {latestCompression.stage}
                  </span>
                )}
              </div>
              {latestCompression ? (
                <>
                  <div className="flex items-center justify-between">
                    <span className="text-gray-500">压缩前</span>
                    <span className="text-gray-700 font-mono">{latestCompression.before.toLocaleString()} chars</span>
                  </div>
                  <div className="flex items-center justify-between">
                    <span className="text-gray-500">压缩后</span>
                    <span className="text-green-700 font-mono">{latestCompression.after.toLocaleString()} chars</span>
                  </div>
                  <div className="flex items-center justify-between">
                    <span className="text-gray-500">节省</span>
                    <span className="text-green-700 font-mono">
                      {latestCompression.saved.toLocaleString()} ({Math.round((1 - latestCompression.ratio) * 100)}%)
                    </span>
                  </div>
                  <div className="w-full h-2 rounded bg-gray-100 overflow-hidden">
                    <div
                      className="h-full bg-green-500"
                      style={{ width: `${Math.max(0, Math.min(100, (1 - latestCompression.ratio) * 100))}%` }}
                    />
                  </div>
                </>
              ) : (
                <div className="text-gray-400 text-center py-3">暂无精简数据</div>
              )}
            </div>
          </div>
        );
      case 'trace':
        return <StepTraceTimeline events={stepTraceEvents} />;
      case 'evidence':
        return (
          <div className="space-y-3">
            <div className="text-xs text-gray-500">证据与引用</div>
            {messages.length === 0 ? (
              <div className="text-xs text-gray-400 text-center py-6">暂无证据</div>
            ) : (
              messages
                .filter((m) => m.metadata?.references || m.metadata?.sources)
                .map((m) => (
                  <div
                    key={m.id}
                    className="rounded-md border border-gray-200 p-3 text-xs space-y-2"
                  >
                    {m.metadata?.references && m.metadata.references.length > 0 && (
                      <div>
                        <div className="font-medium text-gray-700 mb-1">参考文献</div>
                        <ul className="list-disc pl-4 space-y-0.5">
                          {m.metadata.references.map((r, i) => (
                            <li key={i} className="text-gray-600">
                              {r.title}
                            </li>
                          ))}
                        </ul>
                      </div>
                    )}
                    {m.metadata?.sources && m.metadata.sources.length > 0 && (
                      <div>
                        <div className="font-medium text-gray-700 mb-1">片段证据</div>
                        <ul className="space-y-0.5">
                          {m.metadata.sources.map((s, i) => (
                            <li key={i} className="text-gray-600 line-clamp-2">
                              · {s.text}
                            </li>
                          ))}
                        </ul>
                      </div>
                    )}
                  </div>
                ))
            )}
          </div>
        );
      case 'analysis':
        return (
          <div className="space-y-3">
            <div className="text-xs text-gray-500">分析概要</div>
            <div className="rounded-md border border-gray-200 p-3 text-xs space-y-2">
              <div className="flex items-center gap-1.5 text-gray-700">
                <Target className="w-3.5 h-3.5 text-primary-500" />
                当前能力：{capabilityMeta.label}
              </div>
              {currentCapabilityInfo && (
                <>
                  <div>
                    预计延迟：
                    <span className="font-medium text-gray-700">
                      {currentCapabilityInfo.latency_ms}ms
                    </span>
                  </div>
                  <div>
                    成本等级：
                    <span className="font-medium text-gray-700">
                      {currentCapabilityInfo.cost_level}
                    </span>
                  </div>
                </>
              )}
              <div>
                会话状态：
                <span className="inline-flex items-center gap-1 ml-1 text-green-600">
                  <CheckCircle2 className="w-3 h-3" /> 正常
                </span>
              </div>
            </div>
          </div>
        );
      default:
        return null;
    }
  };

  const RightPanel = (
    <div className="h-full flex flex-col">
      <div className="flex items-center gap-0.5 px-2 py-2 border-b border-gray-100 overflow-x-auto">
        {RIGHT_TABS.map((tab) => {
          const Icon = tab.icon;
          const isActive = activeTab === tab.key;
          return (
            <button
              key={tab.key}
              onClick={() => setActiveTab(tab.key)}
              className={clsx(
                'inline-flex items-center gap-1 px-2.5 py-1.5 text-xs font-medium rounded-md transition-colors whitespace-nowrap',
                isActive
                  ? 'bg-primary-50 text-primary-700'
                  : 'text-gray-500 hover:text-gray-700 hover:bg-gray-50',
              )}
            >
              <Icon className="w-3.5 h-3.5" />
              {tab.label}
            </button>
          );
        })}
      </div>
      <div className="flex-1 overflow-y-auto p-3">{renderTabContent()}</div>
    </div>
  );

  const CapabilitySelector = (
    <div className="relative" ref={capabilityRef}>
      <button
        onClick={() => setCapabilityMenuOpen((v) => !v)}
        className="inline-flex items-center gap-1.5 px-3 py-1.5 text-sm font-medium rounded-md bg-gray-100 hover:bg-gray-200 text-gray-700 transition-colors"
        title={capabilityMeta.description}
      >
        <CurrentCapIcon className="w-4 h-4 text-primary-600" />
        <span>{capabilityMeta.label}</span>
        <ChevronRight
          className={clsx(
            'w-3 h-3 text-gray-400 transition-transform',
            capabilityMenuOpen && 'rotate-90',
          )}
        />
      </button>
      {capabilityMenuOpen && (
        <div className="absolute top-full left-0 mt-1 z-30 w-64 rounded-lg bg-white border border-gray-200 shadow-lg py-1">
          {(Object.keys(CAPABILITY_META) as CapabilityType[]).map((key) => {
            const meta = CAPABILITY_META[key];
            const CapIcon = meta.icon;
            const isActive = capability === key;
            const info = availableCapabilities.find((c) => c.type === key);
            return (
              <button
                key={key}
                onClick={() => {
                  setCapability(key);
                  setCapabilityMenuOpen(false);
                }}
                className={clsx(
                  'w-full flex items-start gap-2 px-3 py-2 text-left transition-colors',
                  isActive ? 'bg-primary-50' : 'hover:bg-gray-50',
                )}
              >
                <CapIcon
                  className={clsx(
                    'w-4 h-4 mt-0.5',
                    isActive ? 'text-primary-600' : 'text-gray-500',
                  )}
                />
                <div className="flex-1 min-w-0">
                  <div className="flex items-center gap-1.5">
                    <span
                      className={clsx(
                        'text-sm font-medium',
                        isActive ? 'text-primary-700' : 'text-gray-800',
                      )}
                    >
                      {meta.label}
                    </span>
                    {isActive && <CheckCircle2 className="w-3.5 h-3.5 text-primary-600" />}
                  </div>
                  <div className="text-xs text-gray-500">{meta.description}</div>
                  {info && (
                    <div className="text-[10px] text-gray-400 mt-0.5">
                      延迟 ~{info.latency_ms}ms · 成本 {info.cost_level}
                    </div>
                  )}
                </div>
              </button>
            );
          })}
        </div>
      )}
    </div>
  );

  const EmptyMessages = (
    <div className="flex-1 flex items-center justify-center py-16">
      <EmptyState
        icon={Sparkles}
        title={currentSessionId ? '暂无消息，开启对话' : '请选择或新建会话'}
        description={
          currentSessionId
            ? `当前能力：${capabilityMeta.label}。输入你的问题，Agent 将自动路由能力为你服务。`
            : '在左侧选择已有会话，或点击 + 新建统一智能会话'
        }
      />
    </div>
  );

  const MessageList = (
    <div className="flex-1 min-h-0 overflow-y-auto px-4 py-3">
      {messages.length === 0 ? (
        EmptyMessages
      ) : (
        <div className="space-y-3 max-w-3xl mx-auto">
          {messages.map(renderMessage)}
          {isSending && (
            <div className="flex items-center gap-2 py-3 text-sm text-gray-500">
              <Loader2 className="w-4 h-4 animate-spin" />
              <span>Agent 正在思考…</span>
            </div>
          )}
          <div ref={messagesEndRef} />
        </div>
      )}
    </div>
  );

  const Composer = (
    <div className="border-t border-gray-100 bg-white px-4 py-3">
      <div className="max-w-3xl mx-auto space-y-2">
        {messages.length === 0 && (
          <div className="space-y-3">
            <div className="flex items-center gap-1.5 text-xs text-gray-500">
              <Sparkles className="w-3.5 h-3.5 text-primary-500" />
              <span>试试以下引导操作，快速开始：</span>
            </div>
            {suggestions.length === 0 ? (
              <div className="grid grid-cols-1 sm:grid-cols-3 gap-2">
                {[
                  { action: 'deep_analysis', label: '深入分析', desc: '对问题进行深度科学分析' },
                  { action: 'run_pipeline', label: '运行流水线', desc: '执行一键药物发现流水线' },
                  { action: 'search_literature', label: '检索文献', desc: '搜索相关科学文献' },
                ].map((s) => (
                  <button
                    key={s.action}
                    onClick={() => applySuggestion({ action: s.action, label: s.label, description: s.desc, capability: 'auto', priority: 'high' })}
                    className="text-left rounded-lg border border-gray-200 bg-white hover:border-primary-300 hover:bg-primary-50/50 transition-colors p-2.5"
                  >
                    <div className="text-xs font-medium text-gray-800">{s.label}</div>
                    <div className="text-[11px] text-gray-500 mt-0.5">{s.desc}</div>
                  </button>
                ))}
              </div>
            ) : (
              <div className="grid grid-cols-1 sm:grid-cols-3 gap-2">
                {suggestions.slice(0, 6).map((s, i) => (
                  <button
                    key={i}
                    onClick={() => applySuggestion(s)}
                    className="text-left rounded-lg border border-gray-200 bg-white hover:border-primary-300 hover:bg-primary-50/50 transition-colors p-2.5"
                  >
                    <div className="text-xs font-medium text-gray-800">{s.label}</div>
                    <div className="text-[11px] text-gray-500 mt-0.5">{s.description}</div>
                  </button>
                ))}
              </div>
            )}
          </div>
        )}
        <div
          className={clsx(
            'rounded-xl border bg-white transition-all',
            error ? 'border-red-300' : 'border-gray-200 focus-within:border-primary-400 focus-within:shadow-sm',
          )}
        >
          <textarea
            value={inputValue}
            onChange={(e) => setInputValue(e.target.value)}
            onKeyDown={handleKeyDown}
            rows={2}
            placeholder={`以「${capabilityMeta.label}」能力回答…（Enter 发送，Shift+Enter 换行）`}
            className="w-full resize-none bg-transparent px-3.5 py-2.5 text-sm text-gray-800 placeholder:text-gray-400 focus:outline-none"
          />
          <div className="flex items-center justify-between gap-2 px-3 py-2 border-t border-gray-100">
            <div className="flex items-center gap-2 text-[11px] text-gray-500">
              <CurrentCapIcon className="w-3.5 h-3.5 text-primary-500" />
              <span>{capabilityMeta.label}</span>
              {currentProject && (
                <>
                  <span className="text-gray-300">·</span>
                  <span>项目：{currentProject.name}</span>
                </>
              )}
            </div>
            <button
              onClick={handleSend}
              disabled={isSending || !inputValue.trim()}
              className={clsx(
                'inline-flex items-center gap-1.5 px-3 py-1.5 text-sm font-medium rounded-md transition-colors',
                isSending || !inputValue.trim()
                  ? 'bg-gray-100 text-gray-400 cursor-not-allowed'
                  : 'bg-primary-600 hover:bg-primary-700 text-white',
              )}
            >
              {isSending ? (
                <>
                  <Loader2 className="w-4 h-4 animate-spin" />
                  发送中
                </>
              ) : (
                <>
                  <Send className="w-4 h-4" />
                  发送
                </>
              )}
            </button>
          </div>
        </div>
        {error && (
          <div className="flex items-start gap-2 rounded-md border border-red-200 bg-red-50 px-3 py-2 text-xs text-red-700">
            <AlertCircle className="w-4 h-4 mt-0.5 flex-shrink-0" />
            <div className="flex-1">{error}</div>
            <button
              onClick={clearError}
              className="text-red-500 hover:text-red-700"
              aria-label="清除错误"
            >
              <X className="w-4 h-4" />
            </button>
          </div>
        )}
      </div>
    </div>
  );

  const CenterContent = (
    <div className="flex-1 flex flex-col min-w-0">
      <div className="flex items-center justify-between gap-2 px-4 py-2 border-b border-gray-100">
        <div className="flex items-center gap-2 min-w-0">
          <h2 className="text-sm font-semibold text-gray-800 truncate">
            {currentSessionId
              ? sessions.find((s) => s.id === currentSessionId)?.title ?? '当前会话'
              : '未选择会话'}
          </h2>
          <span className="text-xs text-gray-400 flex-shrink-0">
            · {messages.length} 条
          </span>
        </div>
      </div>
      {workflowStatus && (
        <div className="px-4 py-1.5 bg-gradient-to-r from-indigo-50 to-purple-50 border-b border-gray-100">
          <div className="flex items-center gap-3 text-xs">
            <div className="flex items-center gap-1">
              <Brain className="w-3.5 h-3.5 text-indigo-600" />
              <span className="font-medium text-gray-700" suppressHydrationWarning>{workflowStatus.brain}</span>
            </div>
            <ChevronRight className="w-3 h-3 text-gray-400" />
            <div className="flex items-center gap-1 flex-wrap">
              {workflowStatus.hands?.map((h, i) => (
                <span key={i} className="inline-flex items-center gap-0.5 px-1.5 py-0.5 bg-white border border-gray-200 rounded text-[10px] text-gray-600">
                  <Hand className="w-2.5 h-2.5 text-green-600" />
                  {h.icon || '🔧'} {h.name}
                </span>
              ))}
            </div>
            <div className="ml-auto flex items-center gap-1">
              <span className="inline-flex items-center gap-0.5 px-1.5 py-0.5 bg-green-100 text-green-700 rounded text-[10px]">
                <CheckCircle2 className="w-2.5 h-2.5" />
                {workflowStatus.status === 'completed' ? '已完成' : '运行中'}
              </span>
            </div>
          </div>
        </div>
      )}
      {MessageList}
      {messages.length > 0 && suggestions.length > 0 && (
        <div className="border-t border-gray-100 bg-gray-50 px-4 py-2">
          <div className="max-w-3xl mx-auto space-y-2">
            <div className="flex items-center gap-1.5 text-xs text-gray-500">
              <Sparkles className="w-3.5 h-3.5 text-primary-500" />
              <span>推荐下一步：</span>
            </div>
            <div className="grid grid-cols-1 sm:grid-cols-2 gap-2">
              {suggestions.map((s) => (
                <SuggestionCard
                  key={s.action}
                  suggestion={s}
                  onClick={() => applySuggestion(s)}
                />
              ))}
            </div>
          </div>
        </div>
      )}
      {Composer}
    </div>
  );

  const SessionSidebar = (
    <Card className="h-full flex flex-col">
      <div className="flex items-center justify-between px-4 py-3 border-b border-gray-100">
        <div className="flex items-center gap-1.5">
          <Sparkles className="w-4 h-4 text-primary-500" />
          <h3 className="text-sm font-semibold text-gray-800">智能会话</h3>
        </div>
        <button
          onClick={() => setShowCreateConfirm(true)}
          className="p-1 rounded hover:bg-gray-100 text-primary-600 transition-colors"
          title="新建会话"
        >
          <Plus className="w-4 h-4" />
        </button>
      </div>
      <div className="flex-1 overflow-y-auto">
        {sessions.length === 0 ? (
          <div className="text-center py-8 text-xs text-gray-400 px-4">
            暂无会话，点击 + 新建
          </div>
        ) : (
          <ul className="divide-y divide-gray-50">
            {sessions.map((s) => {
              const isActive = s.id === currentSessionId;
              return (
                <li key={s.id}>
                  <button
                    onClick={() => handleSelectSession(s.id)}
                    className={clsx(
                      'w-full text-left px-4 py-2.5 transition-colors',
                      isActive
                        ? 'bg-primary-50 hover:bg-primary-50'
                        : 'hover:bg-gray-50',
                    )}
                  >
                    <div className="flex items-center justify-between gap-2">
                      <div className="text-xs font-medium text-gray-800 truncate">
                        {s.title}
                      </div>
                      {s.primary_mode && (
                        <span className="text-[10px] px-1.5 py-0.5 rounded bg-gray-100 text-gray-600 flex-shrink-0">
                          {CAPABILITY_META[s.primary_mode as CapabilityType]?.label ||
                            s.primary_mode}
                        </span>
                      )}
                    </div>
                    <div className="text-[10px] text-gray-400 mt-0.5">
                      {s.message_count} 条消息
                      {s.last_message_at &&
                        ` · ${new Date(s.last_message_at).toLocaleString()}`}
                    </div>
                  </button>
                </li>
              );
            })}
          </ul>
        )}
      </div>
    </Card>
  );

  const PanelButton = (props: { className?: string }) => (
    <button
      onClick={() => setPanelOpen(true)}
      className={clsx(
        'p-1.5 rounded-md bg-white border border-gray-200 hover:bg-gray-50 text-gray-600 shadow-sm',
        props.className,
      )}
      title="打开信息面板"
    >
      <PanelRight className="w-4 h-4" />
    </button>
  );

  return (
    <div className="h-full flex flex-col relative">
      <div className="flex items-center justify-between px-4 py-2 bg-white border-b border-gray-100">
        <div className="flex items-center gap-3">
          <h1 className="text-lg font-semibold text-gray-800">智能Agent工作台</h1>
          {CapabilitySelector}
        </div>
      </div>

      <div className="flex-1 flex relative overflow-hidden">
        {isDesktop && (
          <>
            <aside className="w-64 flex-shrink-0">{SessionSidebar}</aside>

            <section className="flex-1 flex flex-col min-w-0">{CenterContent}</section>

            <aside className="w-96 flex-shrink-0">
              <div className="h-full bg-white rounded-lg shadow-card border border-gray-100 overflow-hidden">
                {RightPanel}
              </div>
            </aside>
          </>
        )}

        {isTablet && (
          <div className="flex w-full gap-4 p-3">
            <aside className="w-60 flex-shrink-0">{SessionSidebar}</aside>

            <section className="flex-1 flex flex-col min-w-0 relative">
              {CenterContent}
              <div className="absolute top-3 right-3 z-10">
                <PanelButton />
              </div>
            </section>

            {panelOpen && (
              <div
                className="fixed inset-0 z-40 bg-black/30"
                onClick={() => setPanelOpen(false)}
              >
                <aside
                  className="absolute right-0 top-0 bottom-0 w-96 max-w-[85vw] bg-white shadow-2xl"
                  onClick={(e) => e.stopPropagation()}
                >
                  <div className="flex items-center justify-between px-4 py-2 border-b border-gray-100">
                    <h3 className="text-sm font-semibold text-gray-800">信息面板</h3>
                    <button
                      onClick={() => setPanelOpen(false)}
                      className="p-1 rounded hover:bg-gray-100 text-gray-500"
                    >
                      <X className="w-4 h-4" />
                    </button>
                  </div>
                  <div className="h-[calc(100%-41px)]">{RightPanel}</div>
                </aside>
              </div>
            )}
          </div>
        )}

        {isMobile && (
          <section className="flex-1 flex flex-col min-w-0 relative">
            {CenterContent}
            <div className="absolute top-3 right-3 flex gap-1 z-10">
              <PanelButton />
              <button
                onClick={() => setSidebarOpen(true)}
                className="p-1.5 rounded-md bg-white border border-gray-200 hover:bg-gray-50 text-gray-600 shadow-sm"
                title="会话列表"
              >
                <Menu className="w-4 h-4" />
              </button>
            </div>

            {sidebarOpen && (
              <div
                className="fixed inset-0 z-40 bg-black/40"
                onClick={() => setSidebarOpen(false)}
              >
                <aside
                  className="absolute left-0 top-0 bottom-0 w-72 max-w-[85vw] bg-white shadow-2xl"
                  onClick={(e) => e.stopPropagation()}
                >
                  <div className="flex items-center justify-between px-4 py-2 border-b border-gray-100">
                    <h3 className="text-sm font-semibold text-gray-800">会话列表</h3>
                    <button
                      onClick={() => setSidebarOpen(false)}
                      className="p-1 rounded hover:bg-gray-100 text-gray-500"
                    >
                      <X className="w-4 h-4" />
                    </button>
                  </div>
                  <div className="h-[calc(100%-41px)]">{SessionSidebar}</div>
                </aside>
              </div>
            )}

            {panelOpen && (
              <div
                className="fixed inset-0 z-40 bg-black/40"
                onClick={() => setPanelOpen(false)}
              >
                <aside
                  className="absolute right-0 top-0 bottom-0 w-full sm:w-96 max-w-[100vw] bg-white shadow-2xl"
                  onClick={(e) => e.stopPropagation()}
                >
                  <div className="flex items-center justify-between px-4 py-2 border-b border-gray-100">
                    <h3 className="text-sm font-semibold text-gray-800">信息面板</h3>
                    <button
                      onClick={() => setPanelOpen(false)}
                      className="p-1 rounded hover:bg-gray-100 text-gray-500"
                    >
                      <X className="w-4 h-4" />
                    </button>
                  </div>
                  <div className="h-[calc(100%-41px)]">{RightPanel}</div>
                </aside>
              </div>
            )}
          </section>
        )}
      </div>

      {error && !isSending && (
        <div className="fixed bottom-4 left-1/2 -translate-x-1/2 z-50 bg-red-600 text-white text-sm px-4 py-2 rounded shadow-lg flex items-center gap-2 max-w-[90vw]">
          <AlertCircle className="w-4 h-4" />
          <span className="truncate">{error}</span>
          <button
            onClick={clearError}
            className="text-white/80 hover:text-white shrink-0"
            aria-label="关闭"
          >
            <X className="w-4 h-4" />
          </button>
        </div>
      )}

      {showCreateConfirm && (
        <div
          className="fixed inset-0 z-50 bg-black/40 flex items-center justify-center p-4"
          onClick={() => setShowCreateConfirm(false)}
        >
          <div
            className="bg-white rounded-lg shadow-xl w-full max-w-sm p-4"
            onClick={(e) => e.stopPropagation()}
          >
            <h3 className="text-base font-semibold text-gray-800 mb-1">新建会话</h3>
            <p className="text-sm text-gray-600 mb-4">
              将以「{capabilityMeta.label}」能力创建一个新的统一智能会话。
            </p>
            <div className="flex justify-end gap-2">
              <button
                onClick={() => setShowCreateConfirm(false)}
                className="px-3 py-1.5 text-sm text-gray-600 hover:bg-gray-100 rounded-md"
              >
                取消
              </button>
              <button
                onClick={handleCreateSession}
                className="px-3 py-1.5 text-sm bg-primary-600 text-white rounded-md hover:bg-primary-700"
              >
                创建
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}

function SuggestionCard({
  suggestion,
  onClick,
}: {
  suggestion: SuggestionAction;
  onClick: () => void;
}) {
  const isPrimary = suggestion.priority === 'high';
  return (
    <button
      onClick={onClick}
      className={clsx(
        'w-full text-left rounded-lg border p-3 transition-all',
        'hover:border-primary-300 hover:bg-primary-50/50 hover:shadow-sm',
        isPrimary ? 'border-primary-200 bg-primary-50/40' : 'border-gray-200 bg-white',
      )}
    >
      <div className="flex items-start gap-2">
        <div
          className={clsx(
            'w-7 h-7 flex-shrink-0 rounded-md flex items-center justify-center',
            isPrimary ? 'bg-primary-100 text-primary-700' : 'bg-gray-100 text-gray-600',
          )}
        >
          {isPrimary ? <Zap className="w-3.5 h-3.5" /> : <Sparkles className="w-3.5 h-3.5" />}
        </div>
        <div className="flex-1 min-w-0">
          <div className="text-sm font-medium text-gray-800 truncate">{suggestion.label}</div>
          <div className="text-xs text-gray-500 mt-0.5 line-clamp-2">
            {suggestion.description}
          </div>
        </div>
        <ChevronRight className="w-4 h-4 text-gray-400 flex-shrink-0 mt-1" />
      </div>
    </button>
  );
}
