'use client';

import { useState, useEffect, useRef, useCallback, useMemo } from 'react';
import { usePathname } from 'next/navigation';
import { useUnifiedAgent } from '@/hooks/useUnifiedAgent';
import type { CapabilityType, UnifiedMessage } from '@/hooks/useUnifiedAgent';
import { useAppStore } from '@/lib/store';
import ReasoningTraces from './ReasoningTraces';
import {
  Sparkles,
  X,
  Send,
  Loader2,
  ChevronRight,
  FileText,
  Cpu,
  Bot,
  Zap,
} from 'lucide-react';
import clsx from 'clsx';

const CAPABILITY_META: Record<CapabilityType, { label: string; icon: typeof Sparkles; color: string }> = {
  qa: { label: 'AI问答', icon: FileText, color: 'blue' },
  reasoning: { label: '科学推理', icon: Cpu, color: 'purple' },
  agent: { label: 'Agent执行', icon: Bot, color: 'green' },
  auto: { label: '自动判断', icon: Sparkles, color: 'indigo' },
};

const WORKFLOW_VISUAL_MAP: Record<string, { brain: string; hands: { name: string; icon: string }[] }> = {
  qa: {
    brain: '知识库问答引擎',
    hands: [
      { name: '文档检索', icon: '📚' },
      { name: '知识匹配', icon: '🎯' },
    ],
  },
  reasoning: {
    brain: '科学推理引擎',
    hands: [
      { name: '假设生成', icon: '💡' },
      { name: '通路分析', icon: '🔬' },
      { name: '文献检索', icon: '📖' },
    ],
  },
  agent: {
    brain: 'Agent调度中心',
    hands: [
      { name: '任务规划', icon: '📋' },
      { name: '工具调用', icon: '🔧' },
      { name: '执行引擎', icon: '⚙️' },
    ],
  },
};

function buildSuggestedQuestions(
  pathname: string,
  projectName?: string
): { icon: string; question: string; capability: CapabilityType }[] {
  const ctx = projectName ? `关于「${projectName}」项目` : '';
  const map: Record<string, { icon: string; question: string; capability: CapabilityType }[]> = {
    '/workbench/molecules': [
      { icon: '🔬', question: `${ctx}分析当前分子库的成药性和优化方向`, capability: 'reasoning' },
      { icon: '💡', question: `${ctx}针对当前分子设计新的类似物`, capability: 'agent' },
    ],
    '/workbench/hypotheses': [
      { icon: '🧬', question: `${ctx}生成对立假设并进行辩论验证`, capability: 'reasoning' },
    ],
    '/workbench/targets': [
      { icon: '🎯', question: `${ctx}发现新的治疗靶点并验证`, capability: 'reasoning' },
      { icon: '🔬', question: `${ctx}分析靶点的结构与功能`, capability: 'qa' },
    ],
    '/workbench/experiments': [
      { icon: '📊', question: `${ctx}分析实验结果并设计下一步方案`, capability: 'reasoning' },
    ],
    '/workbench/docking': [
      { icon: '🔗', question: `${ctx}分析分子对接结果和结合模式`, capability: 'reasoning' },
    ],
    '/workbench': [
      { icon: '💊', question: `${ctx}启动一键药物发现流水线`, capability: 'agent' },
      { icon: '🧬', question: `${ctx}综合分析项目数据并生成假设`, capability: 'reasoning' },
    ],
  };
  for (const key of Object.keys(map)) {
    if (pathname.startsWith(key)) return map[key];
  }
  return [
    { icon: '💊', question: `${ctx}综合分析项目数据，生成研究假设`, capability: 'reasoning' },
    { icon: '🔍', question: `${ctx}搜索相关科学文献和靶点`, capability: 'qa' },
    { icon: '⚙️', question: `${ctx}执行药物发现流水线`, capability: 'agent' },
  ];
}

function getContextLabel(pathname: string): string {
  const map: Record<string, string> = {
    '/workbench/molecules': '分子库',
    '/workbench/hypotheses': '假设生成',
    '/workbench/treatments': '治疗方案',
    '/workbench/experiments': '实验设计',
    '/workbench/targets': '靶点发现',
    '/workbench/data': '数据管理',
    '/workbench/docking': '分子对接',
    '/workbench': '工作台',
    '/dashboard': '全局看板',
  };
  for (const key of Object.keys(map)) {
    if (pathname.startsWith(key)) return map[key];
  }
  return '工作流';
}

export default function ScientistCopilot() {
  const pathname = usePathname();
  const { copilotOpen, setCopilotOpen, currentProject } = useAppStore();
  const [mounted, setMounted] = useState(false);

  const agent = useUnifiedAgent();
  const messages = agent.messages;
  const inputValue = agent.inputValue;
  const capability = agent.capability;
  const suggestions = agent.suggestions;
  const error = agent.error;
  const isSending = agent.isSending;
  const sendMessage = agent.sendMessage;
  const createNewSession = agent.createNewSession;
  const setCapability = agent.setCapability;
  const applySuggestion = agent.applySuggestion;
  const setInputValue = agent.setInputValue;
  const clearError = agent.clearError;
  const workflowStatus = agent.workflowStatus;
  const reasoningTraces = agent.reasoningTraces;
  const sendProgress = agent.sendProgress;
  const isLoadingTraces = agent.isLoadingTraces;

  const messagesEndRef = useRef<HTMLDivElement>(null);

  const suggestedQuestions = useMemo(
    () => buildSuggestedQuestions(pathname, currentProject?.name),
    [pathname, currentProject?.name]
  );
  const contextLabel = useMemo(() => getContextLabel(pathname), [pathname]);
  const capabilityMeta = CAPABILITY_META[capability];
  const CurrentCapIcon = capabilityMeta.icon;

  const workflowVisual = useMemo(() => {
    const cap = workflowStatus?.step || capability;
    return WORKFLOW_VISUAL_MAP[cap] || WORKFLOW_VISUAL_MAP.qa;
  }, [workflowStatus, capability]);

  useEffect(() => {
    setMounted(true);
  }, []);

  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [messages]);

  const handleSend = useCallback(async () => {
    if (!inputValue.trim() || isSending) return;
    await sendMessage();
  }, [inputValue, isSending, sendMessage]);

  const handleKeyDown = useCallback(
    (e: React.KeyboardEvent<HTMLTextAreaElement>) => {
      if (e.key === 'Enter' && !e.shiftKey) {
        e.preventDefault();
        handleSend();
      }
    },
    [handleSend]
  );

  const handleQuickQuestion = useCallback(
    async (question: string, cap: CapabilityType) => {
      setCapability(cap);
      await sendMessage(question, cap);
    },
    [setCapability, sendMessage]
  );

  const renderMessageContent = (msg: UnifiedMessage) => {
    if (msg.metadata?.sources && msg.metadata.sources.length > 0) {
      return (
        <div className="space-y-1.5">
          <p className="whitespace-pre-wrap leading-relaxed">{msg.content}</p>
          <div className="rounded-md border border-gray-100 bg-gray-50 p-2">
            <div className="text-[10px] font-medium text-gray-500 mb-0.5">引用来源</div>
            {msg.metadata.sources.slice(0, 3).map((s, i) => (
              <div key={i} className="text-[11px] text-gray-500 line-clamp-1">
                · {s.text}
              </div>
            ))}
          </div>
        </div>
      );
    }
    return <p className="whitespace-pre-wrap leading-relaxed">{msg.content}</p>;
  };

  const [expandedTraceMsgId, setExpandedTraceMsgId] = useState<string | null>(null);

  const renderMessage = (msg: UnifiedMessage) => {
    const isUser = msg.role === 'user';
    const capLabel = msg.capability ? CAPABILITY_META[msg.capability]?.label : undefined;
    const hasTraces = !isUser && msg.metadata?.run_id && reasoningTraces.length > 0;
    const showTraces = hasTraces && expandedTraceMsgId === msg.id;

    return (
      <div key={msg.id} className={clsx('flex gap-2 py-2', isUser ? 'flex-row-reverse' : 'flex-row')}>
        <div
          className={clsx(
            'flex-shrink-0 w-6 h-6 rounded-full flex items-center justify-center text-white',
            isUser ? 'bg-primary-500' : 'bg-indigo-600'
          )}
        >
          {isUser ? <span className="text-xs">我</span> : <Sparkles className="w-3.5 h-3.5" />}
        </div>
        <div className={clsx('flex-1 min-w-0 max-w-[85%]', isUser ? 'text-right' : '')}>
          {(capLabel || msg.metadata?.elapsed_seconds != null) && (
            <div
              className="flex items-center gap-1 mb-1 text-[10px] text-gray-400"
              style={{ justifyContent: isUser ? 'flex-end' : 'flex-start' }}
            >
              {capLabel && (
                <span className="px-1.5 py-0.5 rounded bg-gray-100 text-gray-600">{capLabel}</span>
              )}
              {msg.metadata?.elapsed_seconds != null && (
                <span>{msg.metadata.elapsed_seconds.toFixed(1)}s</span>
              )}
              {msg.metadata?.cost_usd != null && (
                <span className="text-amber-500">${msg.metadata.cost_usd.toFixed(4)}</span>
              )}
              {msg.metadata?.run_id && (
                <button
                  onClick={() => setExpandedTraceMsgId(showTraces ? null : msg.id)}
                  className="ml-1 px-1.5 py-0.5 rounded bg-indigo-50 text-indigo-600 hover:bg-indigo-100 transition-colors flex items-center gap-0.5"
                >
                  <Cpu className="w-2.5 h-2.5" />
                  {showTraces ? '收起推理' : '查看推理'}
                </button>
              )}
            </div>
          )}
          <div
            className={clsx(
              'inline-block rounded-2xl px-3 py-2 text-sm',
              isUser
                ? 'bg-primary-500 text-white rounded-tr-sm'
                : 'bg-white border border-gray-200 text-gray-800 rounded-tl-sm'
            )}
          >
            {renderMessageContent(msg)}
          </div>
          {showTraces && !isUser && (
            <ReasoningTraces traces={reasoningTraces} isLoading={isLoadingTraces} />
          )}
        </div>
      </div>
    );
  };

  return (
    <>
      <button
        onClick={() => {
          setCopilotOpen(true);
          if (!messages.length) createNewSession();
        }}
        className={clsx(
          'fixed bottom-6 right-6 z-40 w-14 h-14 rounded-full bg-gradient-to-br from-indigo-500 to-purple-600 text-white shadow-lg hover:shadow-xl hover:scale-105 transition-all flex items-center justify-center group',
          copilotOpen ? 'opacity-0 pointer-events-none scale-0' : 'opacity-100'
        )}
        title="科学推理助手"
        aria-label="打开科学推理助手"
      >
        <Sparkles className="w-6 h-6" />
        <span className="absolute inset-0 rounded-full bg-indigo-400 animate-ping opacity-20" />
      </button>

      <div
        className={clsx(
          'fixed top-0 right-0 h-full w-full sm:w-[520px] bg-white shadow-2xl z-50 flex flex-col transition-transform duration-300',
          copilotOpen ? 'translate-x-0' : 'translate-x-full'
        )}
      >
        <div className="flex items-center justify-between px-4 py-2.5 border-b bg-gradient-to-r from-indigo-50 to-purple-50">
          <div className="flex items-center gap-2 min-w-0">
            <div className="flex items-center justify-center w-8 h-8 rounded-lg bg-gradient-to-br from-indigo-500 to-purple-600 text-white flex-shrink-0">
              <Sparkles className="w-4 h-4" />
            </div>
            <div className="min-w-0">
              <div className="text-sm font-semibold text-gray-800 truncate flex items-center gap-1.5">
                科学推理助手
                <span className="inline-flex items-center gap-0.5 px-1.5 py-0.5 bg-indigo-100 text-indigo-700 rounded text-[10px] font-medium">
                  <span className="inline-flex items-center justify-center w-3 h-3 rounded bg-indigo-600 text-white text-[7px] font-bold">B</span>
                  大脑
                </span>
              </div>
              <div className="text-xs text-gray-500 truncate flex items-center gap-1">
                <span className="px-1.5 py-0.5 bg-purple-100 text-purple-700 rounded text-[10px]" suppressHydrationWarning>
                  {contextLabel}
                </span>
                {currentProject && (
                  <>
                    <ChevronRight className="w-2.5 h-2.5" />
                    <span className="truncate">{currentProject.name}</span>
                  </>
                )}
              </div>
            </div>
          </div>
          <button
            onClick={() => setCopilotOpen(false)}
            className="p-1.5 rounded-lg hover:bg-gray-200 transition flex-shrink-0"
            aria-label="关闭"
          >
            <X className="w-4 h-4 text-gray-600" />
          </button>
        </div>

        <div className="px-3 py-2 border-b bg-indigo-50">
          <div className="flex items-center gap-2 text-xs">
            <div className="flex items-center gap-1">
              <span className="inline-flex items-center justify-center w-4 h-4 rounded bg-indigo-600 text-white text-[9px] font-bold">B</span>
              <span className="font-medium text-indigo-700" suppressHydrationWarning>{workflowVisual.brain}</span>
            </div>
            <span className="text-indigo-400">→</span>
            <div className="flex items-center gap-1 flex-wrap">
              {workflowVisual.hands.map((h, i) => (
                <span
                  key={i}
                  className="inline-flex items-center gap-0.5 px-1.5 py-0.5 bg-white border border-indigo-200 rounded text-[11px] text-gray-700"
                >
                  <span className="text-green-600">🔧</span>
                  {h.icon} {h.name}
                </span>
              ))}
            </div>
            {isSending && (
              <div className="ml-auto flex items-center gap-1 text-[10px] text-blue-500">
                <Loader2 className="w-3 h-3 animate-spin" />
                {sendProgress || '正在协调...'}
              </div>
            )}
          </div>
        </div>

        <div className="flex-1 overflow-y-auto px-3 py-3">
          {messages.length === 0 ? (
            <div className="h-full flex flex-col items-center justify-center py-8">
              <Sparkles className="w-10 h-10 text-indigo-300 mb-3" />
              <div className="text-sm font-medium text-gray-700 mb-1">你好，我是科学推理助手</div>
              <div className="text-xs text-gray-500 mb-4 text-center px-4">
                我可以帮你分析靶点、生成假设、设计实验。试试下面的快捷操作：
              </div>
              <div className="w-full space-y-2 px-2">
                {suggestedQuestions.map((q, i) => {
                  const CapIcon = CAPABILITY_META[q.capability].icon;
                  return (
                    <button
                      key={i}
                      onClick={() => handleQuickQuestion(q.question, q.capability)}
                      className="w-full text-left px-3 py-2.5 rounded-lg border border-gray-200 bg-white hover:border-indigo-300 hover:bg-indigo-50/50 transition-all group"
                    >
                      <div className="flex items-start gap-2">
                        <span className="text-base flex-shrink-0 mt-0.5">{q.icon}</span>
                        <div className="flex-1 min-w-0">
                          <div className="text-xs font-medium text-gray-800 group-hover:text-indigo-700">
                            {q.question}
                          </div>
                          <div className="mt-1 flex items-center gap-1">
                            <span className="inline-flex items-center gap-0.5 px-1 py-0.5 rounded bg-gray-100 text-gray-500 text-[10px]">
                              <CapIcon className="w-2.5 h-2.5" />
                              {CAPABILITY_META[q.capability].label}
                            </span>
                          </div>
                        </div>
                      </div>
                    </button>
                  );
                })}
              </div>
            </div>
          ) : (
            <div className="space-y-1">
              {messages.map(renderMessage)}
              {isSending && (
                <div className="flex gap-2 py-2">
                  <div className="flex-shrink-0 w-6 h-6 rounded-full bg-indigo-600 flex items-center justify-center">
                    <Sparkles className="w-3.5 h-3.5 text-white animate-pulse" />
                  </div>
                  <div className="bg-indigo-50 border border-indigo-100 rounded-2xl rounded-tl-sm px-3 py-2">
                    <div className="flex items-center gap-1.5 text-xs text-indigo-600">
                      <Loader2 className="w-3 h-3 animate-spin" />
                      <span>正在分析中...</span>
                    </div>
                  </div>
                </div>
              )}
              <div ref={messagesEndRef} />
            </div>
          )}
        </div>

        {messages.length > 0 && suggestions.length > 0 && !isSending && (
          <div className="border-t bg-gray-50 px-3 py-2">
            <div className="text-[11px] text-gray-500 mb-1.5 flex items-center gap-1">
              <Zap className="w-3 h-3 text-indigo-500" />
              <span>推荐下一步</span>
            </div>
            <div className="flex gap-1.5 overflow-x-auto pb-1">
              {suggestions.slice(0, 4).map((s, i) => (
                <button
                  key={i}
                  onClick={() => applySuggestion(s)}
                  className="flex-shrink-0 px-2.5 py-1.5 text-[11px] rounded-full border border-gray-200 bg-white hover:border-indigo-300 hover:bg-indigo-50 text-gray-700 transition-colors"
                >
                  {s.label}
                </button>
              ))}
            </div>
          </div>
        )}

        <div className="border-t bg-white px-3 py-2.5">
          {error && (
            <div className="mb-2 flex items-center gap-1.5 rounded-md border border-red-200 bg-red-50 px-2 py-1.5 text-[11px] text-red-700">
              <X className="w-3 h-3" />
              <span className="flex-1">{error}</span>
              <button onClick={clearError} className="text-red-400 hover:text-red-600">
                <X className="w-3 h-3" />
              </button>
            </div>
          )}
          <div className="rounded-xl border border-gray-200 focus-within:border-indigo-400 focus-within:shadow-sm transition-all bg-white">
            <textarea
              value={inputValue}
              onChange={(e) => setInputValue(e.target.value)}
              onKeyDown={handleKeyDown}
              rows={2}
              placeholder="输入你的科学问题...（Enter 发送）"
              className="w-full resize-none bg-transparent px-3 py-2 text-sm text-gray-800 placeholder:text-gray-400 focus:outline-none"
            />
            <div className="flex items-center justify-between px-3 py-1.5 border-t border-gray-100">
              <div className="flex items-center gap-1.5 text-[11px] text-gray-500">
                <CurrentCapIcon className="w-3 h-3 text-indigo-500" />
                <span>{capabilityMeta.label}</span>
              </div>
              <button
                onClick={handleSend}
                disabled={isSending || !inputValue.trim()}
                className={clsx(
                  'inline-flex items-center gap-1 px-3 py-1 text-xs font-medium rounded-md transition-colors',
                  isSending || !inputValue.trim()
                    ? 'bg-gray-100 text-gray-400 cursor-not-allowed'
                    : 'bg-indigo-600 hover:bg-indigo-700 text-white'
                )}
              >
                {isSending ? (
                  <Loader2 className="w-3 h-3 animate-spin" />
                ) : (
                  <Send className="w-3 h-3" />
                )}
                <span>发送</span>
              </button>
            </div>
          </div>
        </div>
      </div>

      {copilotOpen && (
        <div
          className="fixed inset-0 bg-black/20 z-40"
          onClick={() => setCopilotOpen(false)}
        />
      )}
    </>
  );
}
