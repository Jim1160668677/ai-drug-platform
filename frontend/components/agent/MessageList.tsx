'use client';

import { useRef, useCallback } from 'react';
import { Virtuoso, type VirtuosoHandle } from 'react-virtuoso';
import { Sparkles, Brain } from 'lucide-react';
import ReactMarkdown from 'react-markdown';
import type { AgentMessage } from '@/types/agent';
import { ToolCallBubble } from './ToolCallBubble';

interface MessageListProps {
  messages: AgentMessage[];
  /** 兼容旧接口：自动滚动锚点 ref（虚拟滚动模式下可选） */
  messagesEndRef?: React.RefObject<HTMLDivElement>;
}

function MessageItem({ m }: { m: AgentMessage }) {
  // system 消息（错误/警告）
  if (m.role === 'system') {
    return (
      <div className="flex justify-center my-2">
        <div className="text-xs text-red-600 bg-red-50 border border-red-200 rounded px-3 py-1 max-w-[90%]">
          {m.content}
        </div>
      </div>
    );
  }

  // thought（推理过程，折叠展示）
  if (m.role === 'assistant' && m.thought && !m.toolCalls?.length) {
    return (
      <div className="flex justify-start my-1">
        <div className="max-w-[80%] rounded-lg bg-blue-50 border border-blue-100 px-3 py-2">
          <div className="flex items-center gap-1 text-[10px] text-blue-600 uppercase tracking-wide mb-1">
            <Brain className="w-3 h-3" /> Thought
          </div>
          <div className="text-xs text-blue-900 italic whitespace-pre-wrap">
            {m.thought}
          </div>
        </div>
      </div>
    );
  }

  const isUser = m.role === 'user';

  return (
    <div className={`flex ${isUser ? 'justify-end' : 'justify-start'} my-2`}>
      <div
        className={`max-w-[80%] rounded-lg px-4 py-2 ${
          isUser
            ? 'bg-primary-600 text-white'
            : 'bg-gray-100 text-gray-900'
        }`}
      >
        {isUser ? (
          <div className="whitespace-pre-wrap text-sm">{m.content}</div>
        ) : (
          <div className="markdown-body text-sm">
            <ReactMarkdown>{m.content}</ReactMarkdown>
            {/* 流式响应光标：让用户看到 LLM 正在生成 */}
            {m.isStreaming && (
              <span className="inline-block w-2 h-4 bg-primary-500 ml-0.5 align-middle animate-pulse" />
            )}
          </div>
        )}

        {/* 工具调用气泡 */}
        {!isUser && m.toolCalls && m.toolCalls.length > 0 && (
          <div className="mt-2 space-y-1">
            {m.toolCalls.map((call, i) => {
              const result = m.toolResults?.find((r) => r.step === call.step);
              return (
                <ToolCallBubble key={`${call.step}-${i}`} call={call} result={result} />
              );
            })}
          </div>
        )}

        {/* 元数据 */}
        {!isUser && m.meta && (
          <div className="mt-2 pt-2 border-t border-gray-200 text-xs text-gray-500 flex flex-wrap items-center gap-3">
            {m.meta.token_usage && (
              <span>tokens: {m.meta.token_usage.total.toLocaleString()}</span>
            )}
            {m.meta.cost_usd != null && m.meta.cost_usd > 0 && (
              <span>${m.meta.cost_usd.toFixed(4)}</span>
            )}
            {m.meta.duration_sec != null && (
              <span>{m.meta.duration_sec.toFixed(1)}s</span>
            )}
          </div>
        )}
      </div>
    </div>
  );
}

/**
 * MessageList — 消息流（虚拟滚动）
 *
 * 设计来源：2026-07-18-agent-functional-design.md §4.3
 *
 * 聊天面板内消息流采用虚拟滚动（react-virtuoso），单会话支持 1000+ 消息不卡顿。
 * followOutput="smooth" 实现新消息自动滚动到底部。
 */
export function MessageList({ messages, messagesEndRef }: MessageListProps) {
  const virtuosoRef = useRef<VirtuosoHandle>(null);

  // 新消息到达时自动滚动到底部
  const followOutput = useCallback((isAtBottom: boolean) => {
    return isAtBottom ? 'smooth' : false;
  }, []);

  // 空状态
  if (messages.length === 0) {
    return (
      <div className="flex-1 overflow-y-auto px-4 py-3">
        <div className="text-center py-12 text-gray-400">
          <Sparkles className="w-12 h-12 mx-auto mb-2 opacity-50" />
          <p className="text-sm">向 AI Agent 提问，它会自主规划并调用工具完成任务</p>
          <div className="mt-3 text-xs space-y-1">
            <p>· &quot;帮我发现 EGFR 耐药相关靶点&quot;</p>
            <p>· &quot;设计针对 B7H3 的小分子化合物&quot;</p>
            <p>· &quot;检索 KRAS G12C 抑制剂最新文献&quot;</p>
          </div>
        </div>
        {/* 兼容旧 ref */}
        <div ref={messagesEndRef} />
      </div>
    );
  }

  return (
    <div className="flex-1 overflow-hidden">
      <Virtuoso
        ref={virtuosoRef}
        data={messages}
        followOutput={followOutput}
        className="h-full"
        itemContent={(index, m) => (
          <div className="px-4">
            <MessageItem key={m.id ?? index} m={m} />
          </div>
        )}
        components={{
          // 隐藏滚动条间距
          EmptyPlaceholder: () => <div />,
        }}
      />
      {/* 兼容旧 ref（page.tsx 的 scrollIntoView 调用） */}
      <div ref={messagesEndRef} className="h-0 overflow-hidden" />
    </div>
  );
}
