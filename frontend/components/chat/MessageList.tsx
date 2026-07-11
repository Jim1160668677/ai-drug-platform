'use client';

import { Sparkles, Code2, BookOpen } from 'lucide-react';
import ReactMarkdown from 'react-markdown';
import { Prism as SyntaxHighlighter } from 'react-syntax-highlighter';
import { oneDark } from 'react-syntax-highlighter/dist/esm/styles/prism';
import type { Message } from '@/types/chat';

interface MessageListProps {
  messages: Message[];
  messagesEndRef: React.RefObject<HTMLDivElement>;
}

function MessageItem({ m }: { m: Message }) {
  return (
    <div className={`flex ${m.role === 'user' ? 'justify-end' : 'justify-start'}`}>
      <div
        className={`max-w-[80%] rounded-lg px-4 py-2 ${
          m.role === 'user'
            ? 'bg-primary-600 text-white'
            : 'bg-gray-100 text-gray-900'
        }`}
      >
        {m.role === 'assistant' ? (
          <div className="markdown-body">
            <ReactMarkdown>{m.content}</ReactMarkdown>
          </div>
        ) : (
          <div className="whitespace-pre-wrap">{m.content}</div>
        )}

        {m.role === 'assistant' && (
          <div className="mt-2 pt-2 border-t border-gray-200 text-xs text-gray-500 flex items-center gap-3">
            {m.tier && <span>层级：{m.tier}</span>}
            {m.model && <span>模型：{m.model}</span>}
            {m.cost != null && <span>成本：${m.cost.toFixed(4)}</span>}
            {m.duration != null && <span>耗时：{m.duration.toFixed(1)}s</span>}
          </div>
        )}

        {m.code && (
          <div className="mt-2">
            <div className="flex items-center gap-1 text-xs text-gray-500 mb-1">
              <Code2 className="w-3 h-3" /> 分析代码
            </div>
            <SyntaxHighlighter
              language="python"
              style={oneDark}
              customStyle={{ fontSize: '11px', padding: '8px' }}
            >
              {m.code}
            </SyntaxHighlighter>
          </div>
        )}

        {m.references && m.references.length > 0 && (
          <div className="mt-2">
            <div className="flex items-center gap-1 text-xs text-gray-500 mb-1">
              <BookOpen className="w-3 h-3" /> 参考文献
            </div>
            <ul className="text-xs list-disc pl-4">
              {m.references.map((r, i) => (
                <li key={i}>{r.title || r}</li>
              ))}
            </ul>
          </div>
        )}
      </div>
    </div>
  );
}

export function MessageList({ messages, messagesEndRef }: MessageListProps) {
  return (
    <div className="flex-1 overflow-y-auto space-y-4">
      {messages.length === 0 ? (
        <div className="text-center py-12 text-gray-400">
          <Sparkles className="w-12 h-12 mx-auto mb-2 opacity-50" />
          <p>开始提问吧，例如：</p>
          <p className="text-sm mt-1">&quot;EGFR T790M 耐药机制是什么？&quot;</p>
          <p className="text-sm">&quot;有哪些老药可以新用于 B7H3 靶点？&quot;</p>
        </div>
      ) : (
        messages.map((m, i) => <MessageItem key={i} m={m} />)
      )}
      <div ref={messagesEndRef} />
    </div>
  );
}
