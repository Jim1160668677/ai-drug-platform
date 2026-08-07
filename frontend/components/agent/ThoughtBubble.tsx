'use client';

import { useState } from 'react';
import { Brain, ChevronDown, ChevronRight, Loader2 } from 'lucide-react';
import clsx from 'clsx';

interface ThoughtBubbleProps {
  /** ReAct 推理内容 */
  thought: string;
  /** 当前步数 */
  step?: number;
  /** 最大步数（来自 settings.AGENT_MAX_STEPS，默认 15） */
  maxSteps?: number;
  /** 是否正在思考中（显示动画） */
  isThinking?: boolean;
  /** 默认是否展开 */
  defaultExpanded?: boolean;
}

/**
 * ThoughtBubble — ReAct 引擎推理过程气泡
 *
 * 设计来源：2026-07-18-agent-functional-design.md §4.4
 *
 * 场景：Agent 思考中 → Header 显示旋转图标 + "Agent 思考中..."；消息区显示打字指示器
 *
 * 展示 ReAct 引擎每一步的 Thought（推理过程），支持折叠/展开，
 * 思考中状态显示动画指示器。
 */
export function ThoughtBubble({
  thought,
  step,
  maxSteps = 15,
  isThinking = false,
  defaultExpanded = false,
}: ThoughtBubbleProps) {
  const [expanded, setExpanded] = useState(defaultExpanded || isThinking);

  return (
    <div
      className={clsx(
        'my-1 rounded-lg border px-3 py-2 transition-colors',
        isThinking
          ? 'bg-blue-50 border-blue-200 animate-pulse-subtle'
          : 'bg-blue-50 border-blue-100'
      )}
    >
      <button
        onClick={() => setExpanded(!expanded)}
        className="w-full flex items-center justify-between gap-2"
        aria-expanded={expanded}
      >
        <div className="flex items-center gap-1.5 min-w-0">
          {isThinking ? (
            <Loader2 className="w-3.5 h-3.5 text-blue-500 animate-spin shrink-0" />
          ) : (
            <Brain className="w-3.5 h-3.5 text-blue-500 shrink-0" />
          )}
          <span className="text-[10px] uppercase tracking-wide text-blue-600 font-medium">
            {isThinking ? 'Agent 思考中' : 'Thought'}
          </span>
          {step != null && (
            <span className="text-[10px] text-blue-400">
              步骤 {step}
              {maxSteps > 0 && `/${maxSteps}`}
            </span>
          )}
        </div>
        {expanded ? (
          <ChevronDown className="w-3.5 h-3.5 text-blue-400 shrink-0" />
        ) : (
          <ChevronRight className="w-3.5 h-3.5 text-blue-400 shrink-0" />
        )}
      </button>

      {expanded && (
        <div className="mt-2 pt-2 border-t border-blue-100">
          {isThinking && !thought ? (
            // 打字指示器（三个点跳动）
            <div className="flex items-center gap-1 py-1">
              <span className="w-1.5 h-1.5 bg-blue-400 rounded-full animate-bounce [animation-delay:-0.3s]" />
              <span className="w-1.5 h-1.5 bg-blue-400 rounded-full animate-bounce [animation-delay:-0.15s]" />
              <span className="w-1.5 h-1.5 bg-blue-400 rounded-full animate-bounce" />
            </div>
          ) : (
            <div className="text-xs text-blue-900 italic whitespace-pre-wrap break-words">
              {thought}
            </div>
          )}
        </div>
      )}
    </div>
  );
}
