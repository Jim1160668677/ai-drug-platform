'use client';

import { useState, useEffect, useRef } from 'react';
import {
  Loader2,
  CheckCircle2,
  XCircle,
  ChevronDown,
  ChevronRight,
  Wrench,
  Database,
} from 'lucide-react';
import clsx from 'clsx';
import { Prism as SyntaxHighlighter } from 'react-syntax-highlighter';
import { oneDark } from 'react-syntax-highlighter/dist/esm/styles/prism';
import type { ToolCall, ToolResult } from '@/types/agent';

interface ToolCallBubbleProps {
  call: ToolCall;
  result?: ToolResult;
}

/**
 * ToolCallBubble — 工具调用气泡
 *
 * 设计来源：2026-07-18-agent-functional-design.md §4.4
 *
 * 反馈机制：
 * - 工具调用中：Loader2 旋转 + 实时已用时长（每秒更新）
 * - 工具成功：绿色对勾 + 耗时 + 缓存命中标记（如适用）
 * - 工具失败：红色 X + 错误摘要
 */
export function ToolCallBubble({ call, result }: ToolCallBubbleProps) {
  const [expanded, setExpanded] = useState(false);
  // 实时计时：pending 时每秒刷新已用时长
  const [elapsedSec, setElapsedSec] = useState(0);
  const startedAtRef = useRef<number>(Date.now());

  const isPending = !result;
  const isSuccess = result?.success === true;
  const isFailed = result?.success === false;
  // 缓存命中标记（后端 result.cache_hit 或 result.data.cache_hit）
  const cacheHit =
    result?.cache_hit === true ||
    (typeof result?.data === 'object' &&
      result?.data !== null &&
      (result?.data as { cache_hit?: boolean }).cache_hit === true);

  useEffect(() => {
    if (!isPending) {
      // 结果已到，停止计时
      return;
    }
    // 启动计时
    startedAtRef.current = Date.now();
    setElapsedSec(0);
    const timer = setInterval(() => {
      const sec = (Date.now() - startedAtRef.current) / 1000;
      setElapsedSec(sec);
    }, 1000);
    return () => clearInterval(timer);
  }, [isPending]);

  return (
    <div
      className={clsx(
        'my-2 border rounded-md overflow-hidden',
        isFailed
          ? 'border-red-200 bg-red-50'
          : isSuccess
            ? cacheHit
              ? 'border-emerald-200 bg-emerald-50'
              : 'border-gray-200 bg-gray-50'
            : 'border-blue-200 bg-blue-50'
      )}
    >
      <button
        onClick={() => setExpanded(!expanded)}
        className="w-full flex items-center justify-between px-3 py-2 hover:bg-opacity-80 transition-colors"
      >
        <div className="flex items-center gap-2 min-w-0">
          {isPending && <Loader2 className="w-3.5 h-3.5 text-blue-500 animate-spin shrink-0" />}
          {isSuccess && <CheckCircle2 className="w-3.5 h-3.5 text-green-500 shrink-0" />}
          {isFailed && <XCircle className="w-3.5 h-3.5 text-red-500 shrink-0" />}
          <Wrench className="w-3.5 h-3.5 text-gray-500 shrink-0" />
          <span className="text-xs font-mono font-medium text-gray-800 truncate">
            {call.tool}
          </span>
          {call.step != null && (
            <span className="text-[10px] text-gray-400">#{call.step}</span>
          )}
          {/* 耗时展示：pending 显示实时计时，completed 显示最终耗时 */}
          {isPending && elapsedSec > 0 && (
            <span className="text-[10px] text-blue-500 font-mono">
              {elapsedSec.toFixed(1)}s...
            </span>
          )}
          {result?.duration_ms != null && (
            <span
              className={clsx(
                'text-[10px] font-mono',
                cacheHit ? 'text-emerald-600' : 'text-gray-400'
              )}
            >
              {cacheHit ? '<1ms' : `${result.duration_ms}ms`}
            </span>
          )}
          {/* 缓存命中标记 */}
          {cacheHit && (
            <span className="inline-flex items-center gap-0.5 px-1 py-0 rounded bg-emerald-100 text-emerald-700 text-[9px] font-medium">
              <Database className="w-2.5 h-2.5" />
              缓存命中
            </span>
          )}
        </div>
        {expanded ? (
          <ChevronDown className="w-3.5 h-3.5 text-gray-400 shrink-0" />
        ) : (
          <ChevronRight className="w-3.5 h-3.5 text-gray-400 shrink-0" />
        )}
      </button>

      {expanded && (
        <div className="border-t border-gray-200 px-3 py-2 space-y-2 bg-white">
          {call.thought && (
            <div>
              <div className="text-[10px] uppercase tracking-wide text-gray-500 mb-1">
                Thought
              </div>
              <div className="text-xs text-gray-700 italic">{call.thought}</div>
            </div>
          )}
          <div>
            <div className="text-[10px] uppercase tracking-wide text-gray-500 mb-1">
              Parameters
            </div>
            <SyntaxHighlighter
              language="json"
              style={oneDark}
              customStyle={{ fontSize: '11px', padding: '8px', margin: 0 }}
            >
              {JSON.stringify(call.args, null, 2)}
            </SyntaxHighlighter>
          </div>
          {result && (
            <div>
              <div
                className={clsx(
                  'text-[10px] uppercase tracking-wide mb-1',
                  isSuccess ? 'text-green-600' : 'text-red-600'
                )}
              >
                {isSuccess ? 'Result' : 'Error'}
              </div>
              <SyntaxHighlighter
                language="json"
                style={oneDark}
                customStyle={{ fontSize: '11px', padding: '8px', margin: 0 }}
              >
                {JSON.stringify(
                  isSuccess ? result.data : result.error,
                  null,
                  2
                )}
              </SyntaxHighlighter>
            </div>
          )}
        </div>
      )}
    </div>
  );
}
