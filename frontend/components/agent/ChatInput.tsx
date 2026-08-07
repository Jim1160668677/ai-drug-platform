'use client';

import { useState } from 'react';
import { Send, Bot } from 'lucide-react';
import Button from '@/components/ui/Button';

interface ChatInputProps {
  input: string;
  onInputChange: (value: string) => void;
  onSend: () => void;
  isSending: boolean;
  disabled?: boolean;
  placeholder?: string;
  /**
   * 长任务进度（>10s 时显示进度条）
   * 设计来源：2026-07-18-agent-functional-design.md §4.4
   */
  taskProgress?: {
    currentStep: number;
    maxSteps: number;
    durationSec?: number;
  };
}

export function ChatInput({
  input,
  onInputChange,
  onSend,
  isSending,
  disabled,
  placeholder,
  taskProgress,
}: ChatInputProps) {
  const [localInput, setLocalInput] = useState(input);

  // 与父组件受控同步
  const handleChange = (v: string) => {
    setLocalInput(v);
    onInputChange(v);
  };

  const handleSend = () => {
    if (!localInput.trim() || isSending) return;
    onSend();
    setLocalInput('');
    onInputChange('');
  };

  // 是否显示进度条：运行中且 (耗时>10s 或 步数>0)
  // 修复：原逻辑在 durationSec<=10 时短路返回 false，导致 currentStep>0 也被忽略
  const showProgress =
    isSending &&
    !!taskProgress &&
    ((taskProgress.durationSec != null && taskProgress.durationSec > 10) ||
      (taskProgress.currentStep ?? 0) > 0);

  // 进度条百分比：currentStep / maxSteps
  const progressPercent =
    taskProgress && taskProgress.maxSteps > 0
      ? Math.min(100, (taskProgress.currentStep / taskProgress.maxSteps) * 100)
      : 0;

  return (
    <div className="border-t border-gray-200 px-4 py-3 bg-white">
      {/* 长任务进度条 */}
      {showProgress && taskProgress && (
        <div className="mb-2">
          <div className="flex items-center justify-between text-[10px] text-gray-500 mb-1">
            <span className="flex items-center gap-1">
              <Bot className="w-3 h-3 animate-pulse text-primary-600" />
              正在执行任务
            </span>
            <span className="font-mono">
              步骤 {taskProgress.currentStep}/{taskProgress.maxSteps}
              {taskProgress.durationSec != null && (
                <span className="ml-2">· 已耗时 {taskProgress.durationSec.toFixed(1)}s</span>
              )}
            </span>
          </div>
          <div className="h-1.5 bg-gray-100 rounded-full overflow-hidden">
            <div
              className="h-full bg-gradient-to-r from-primary-400 to-primary-600 rounded-full transition-all duration-300 ease-out"
              style={{ width: `${progressPercent}%` }}
            />
          </div>
        </div>
      )}

      <div className="flex gap-2 items-end">
        <div className="flex-1">
          <textarea
            value={localInput}
            onChange={(e) => handleChange(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === 'Enter' && !e.shiftKey) {
                e.preventDefault();
                handleSend();
              }
            }}
            className="w-full px-3 py-2 border border-gray-300 rounded-md text-sm resize-none focus:outline-none focus:ring-2 focus:ring-primary-500"
            rows={2}
            placeholder={placeholder ?? '向 Agent 提问，Enter 发送，Shift+Enter 换行...'}
            disabled={disabled}
          />
        </div>
        <Button
          onClick={handleSend}
          loading={isSending}
          disabled={!localInput.trim() || disabled}
          size="md"
        >
          {isSending ? <Bot className="w-4 h-4" /> : <Send className="w-4 h-4" />}
          {isSending ? '执行中' : '发送'}
        </Button>
      </div>
      <div className="mt-1.5 text-[10px] text-gray-400 flex items-center gap-2">
        <Bot className="w-3 h-3" />
        <span>Agent 模式：自动规划任务、调用工具、流式推送推理过程</span>
      </div>
    </div>
  );
}
