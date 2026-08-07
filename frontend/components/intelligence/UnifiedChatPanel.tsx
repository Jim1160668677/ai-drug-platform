'use client';

/**
 * UnifiedChatPanel — 统一对话面板（组件 4/18）
 *
 * 消息流（虚拟滚动）+ Markdown 渲染 + intent Badge + 元数据。
 * 端点：POST /intelligence/sessions/{id}/chat
 */
import { useRef, useEffect } from 'react';
import { Virtuoso, VirtuosoHandle } from 'react-virtuoso';
import ReactMarkdown from 'react-markdown';
import { Prism as SyntaxHighlighter } from 'react-syntax-highlighter';
import { oneLight } from 'react-syntax-highlighter/dist/esm/styles/prism';
import { Send, User, Brain, AlertCircle, DollarSign, Clock } from 'lucide-react';
import Badge from '@/components/ui/Badge';
import { useAppStore } from '@/lib/store';
import type { IntelligenceMessage } from '@/types/intelligence';

interface UnifiedChatPanelProps {
  sessionId: string;
  messages: IntelligenceMessage[];
  onSend: (message: string, projectId?: string, forceMode?: string) => void;
  isSending: boolean;
  lastIntent?: { mode: string; confidence: number } | null;
}

export default function UnifiedChatPanel({
  sessionId,
  messages,
  onSend,
  isSending,
}: UnifiedChatPanelProps) {
  const virtuosoRef = useRef<VirtuosoHandle>(null);
  const inputRef = useRef<HTMLTextAreaElement>(null);
  const currentProject = useAppStore((s) => s.currentProject);

  // 自动滚动到底部
  useEffect(() => {
    if (messages.length > 0) {
      virtuosoRef.current?.scrollToIndex({
        index: messages.length - 1,
        behavior: 'smooth',
      });
    }
  }, [messages]);

  const handleSend = () => {
    const text = inputRef.current?.value.trim();
    if (!text || isSending) return;
    onSend(text, currentProject?.id);
    if (inputRef.current) inputRef.current.value = '';
  };

  const handleKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault();
      handleSend();
    }
  };

  const renderMessage = (msg: IntelligenceMessage) => {
    const isUser = msg.role === 'user';
    const isSystem = msg.role === 'system';

    return (
      <div
        className={`flex gap-2.5 px-4 py-3 ${isUser ? 'flex-row-reverse' : 'flex-row'}`}
      >
        {/* 头像 */}
        <div
          className={`flex-shrink-0 w-8 h-8 rounded-full flex items-center justify-center ${
            isUser
              ? 'bg-primary-600 text-white'
              : isSystem
                ? 'bg-red-100 text-red-600'
                : 'bg-gray-100 text-gray-600'
          }`}
        >
          {isUser ? (
            <User className="w-4 h-4" />
          ) : isSystem ? (
            <AlertCircle className="w-4 h-4" />
          ) : (
            <Brain className="w-4 h-4" />
          )}
        </div>

        {/* 消息内容 */}
        <div className={`flex-1 min-w-0 max-w-[80%] ${isUser ? 'text-right' : ''}`}>
          {/* 元数据 Badge */}
          {!isUser && !isSystem && (msg.mode || msg.intent) && (
            <div className="flex items-center gap-1.5 mb-1 flex-wrap">
              {msg.mode && <Badge variant="blue">{msg.mode}</Badge>}
              {msg.intent && typeof msg.intent.confidence === 'number' && (
                <span className="text-xs text-gray-400">
                  {(msg.intent.confidence * 100).toFixed(0)}%
                </span>
              )}
              {msg.cost_usd != null && msg.cost_usd > 0 && (
                <span className="flex items-center gap-0.5 text-xs text-gray-400">
                  <DollarSign className="w-3 h-3" />
                  {msg.cost_usd.toFixed(4)}
                </span>
              )}
              {msg.duration_sec != null && msg.duration_sec > 0 && (
                <span className="flex items-center gap-0.5 text-xs text-gray-400">
                  <Clock className="w-3 h-3" />
                  {msg.duration_sec.toFixed(2)}s
                </span>
              )}
            </div>
          )}

          {/* 消息体 */}
          <div
            className={`inline-block px-3.5 py-2 rounded-lg text-sm ${
              isUser
                ? 'bg-primary-600 text-white'
                : isSystem
                  ? 'bg-red-50 text-red-700 border border-red-200'
                  : 'bg-gray-100 text-gray-800'
            }`}
          >
            {isUser || isSystem ? (
              <p className="whitespace-pre-wrap break-words">{msg.content}</p>
            ) : msg.isStreaming && !msg.content ? (
              <span className="inline-flex gap-1">
                <span className="w-2 h-2 bg-gray-400 rounded-full animate-pulse" />
                <span className="w-2 h-2 bg-gray-400 rounded-full animate-pulse" style={{ animationDelay: '0.2s' }} />
                <span className="w-2 h-2 bg-gray-400 rounded-full animate-pulse" style={{ animationDelay: '0.4s' }} />
              </span>
            ) : (
              <div className="prose prose-sm max-w-none break-words text-left">
                <ReactMarkdown
                  components={{
                    code({ className, children, ...props }) {
                      const match = /language-(\w+)/.exec(className || '');
                      return match ? (
                        <SyntaxHighlighter
                          language={match[1]}
                          style={oneLight}
                          PreTag="div"
                        >
                          {String(children).replace(/\n$/, '')}
                        </SyntaxHighlighter>
                      ) : (
                        <code className={className} {...props}>
                          {children}
                        </code>
                      );
                    },
                  }}
                >
                  {msg.content}
                </ReactMarkdown>
              </div>
            )}
          </div>
        </div>
      </div>
    );
  };

  return (
    <div className="flex flex-col h-full bg-white">
      {/* 消息列表 */}
      <div className="flex-1 overflow-hidden">
        {messages.length === 0 ? (
          <div className="flex items-center justify-center h-full text-gray-400 text-sm">
            <div className="text-center">
              <Brain className="w-10 h-10 mx-auto mb-2 text-gray-300" />
              <p>开始一段新的智能对话</p>
              <p className="text-xs mt-1">支持问答、推理、Agent 三种模式</p>
            </div>
          </div>
        ) : (
          <Virtuoso
            ref={virtuosoRef}
            data={messages}
            itemContent={(_, msg) => renderMessage(msg)}
            className="h-full"
          />
        )}
      </div>

      {/* 输入区 */}
      <div className="border-t border-gray-200 p-3">
        <div className="flex items-end gap-2">
          <textarea
            ref={inputRef}
            onKeyDown={handleKeyDown}
            placeholder="输入消息... (Enter 发送, Shift+Enter 换行)"
            rows={1}
            className="flex-1 resize-none px-3 py-2 text-sm border border-gray-300 rounded-lg focus:outline-none focus:ring-1 focus:ring-primary-500 max-h-32"
            style={{ minHeight: '38px' }}
          />
          <button
            onClick={handleSend}
            disabled={isSending}
            className="flex-shrink-0 inline-flex items-center justify-center w-9 h-9 bg-primary-600 text-white rounded-lg hover:bg-primary-700 disabled:bg-gray-300 disabled:cursor-not-allowed transition-colors"
          >
            <Send className="w-4 h-4" />
          </button>
        </div>
      </div>
    </div>
  );
}
