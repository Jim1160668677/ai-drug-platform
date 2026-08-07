'use client';

/**
 * ChatStreamController — 流式对话控制器（组件 5/18）
 *
 * 流式/普通模式开关切换 + 流式状态指示 + 中止按钮。
 * 端点：POST /intelligence/sessions/{id}/stream（由 useIntelligenceChat 内部调用）
 */
import clsx from 'clsx';
import { Zap, ZapOff, Square, Loader2 } from 'lucide-react';

interface ChatStreamControllerProps {
  useStream: boolean;
  onToggleStream: (enabled: boolean) => void;
  streamStatus: 'idle' | 'streaming' | 'done' | 'error';
  onAbort?: () => void;
}

const STATUS_META: Record<string, { label: string; color: string }> = {
  idle: { label: '', color: '' },
  streaming: { label: '流式传输中', color: 'text-green-600' },
  done: { label: '已完成', color: 'text-gray-400' },
  error: { label: '流式错误', color: 'text-red-600' },
};

export default function ChatStreamController({
  useStream,
  onToggleStream,
  streamStatus,
  onAbort,
}: ChatStreamControllerProps) {
  const statusMeta = STATUS_META[streamStatus] ?? STATUS_META.idle;
  const isStreaming = streamStatus === 'streaming';

  return (
    <div className="flex items-center gap-2 px-3 py-1.5 bg-gray-50 border-t border-gray-100">
      {/* 流式开关 */}
      <button
        onClick={() => onToggleStream(!useStream)}
        className={clsx(
          'inline-flex items-center gap-1 px-2 py-1 text-xs font-medium rounded-md transition-colors',
          useStream
            ? 'bg-green-100 text-green-700 hover:bg-green-200'
            : 'bg-gray-200 text-gray-500 hover:bg-gray-300',
        )}
        title={useStream ? '流式模式已开启' : '点击开启流式模式'}
      >
        {useStream ? <Zap className="w-3.5 h-3.5" /> : <ZapOff className="w-3.5 h-3.5" />}
        流式
      </button>

      {/* 流式状态 */}
      {isStreaming && (
        <div className="flex items-center gap-1.5">
          <Loader2 className="w-3 h-3 animate-spin text-green-600" />
          <span className={clsx('text-xs', statusMeta.color)}>{statusMeta.label}</span>
          {onAbort && (
            <button
              onClick={onAbort}
              className="inline-flex items-center gap-0.5 px-1.5 py-0.5 text-xs text-red-600 hover:bg-red-50 rounded"
              title="中止流式"
            >
              <Square className="w-3 h-3" />
              中止
            </button>
          )}
        </div>
      )}

      {!isStreaming && streamStatus === 'error' && (
        <span className={clsx('text-xs', statusMeta.color)}>{statusMeta.label}</span>
      )}

      {/* 提示 */}
      <span className="ml-auto text-xs text-gray-400 hidden sm:inline">
        {useStream ? '实时输出 token' : '等待完整响应'}
      </span>
    </div>
  );
}
