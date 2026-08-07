'use client';

import { Sparkles, MessageSquare, Bot } from 'lucide-react';
import clsx from 'clsx';
import type { IntelligenceMode } from '@/hooks/useUnifiedMode';

interface ModeSelectorProps {
  mode: IntelligenceMode;
  onModeChange: (mode: IntelligenceMode) => void;
}

const MODES: Array<{
  value: IntelligenceMode;
  label: string;
  icon: typeof Sparkles;
  description: string;
}> = [
  {
    value: 'assistant',
    label: '科学助手',
    icon: Sparkles,
    description: '统一智能对话，支持多模式切换',
  },
  {
    value: 'qa',
    label: 'AI 问答',
    icon: MessageSquare,
    description: '研究者提问 → AI 自动执行分析',
  },
  {
    value: 'agent',
    label: 'Agent 工作台',
    icon: Bot,
    description: '自主规划执行，多工具协同',
  },
];

export function ModeSelector({ mode, onModeChange }: ModeSelectorProps) {
  return (
    <div className="flex items-center gap-0.5 p-0.5 bg-gray-100 rounded-lg">
      {MODES.map((m) => {
        const Icon = m.icon;
        const isActive = mode === m.value;
        return (
          <button
            key={m.value}
            onClick={() => onModeChange(m.value)}
            className={clsx(
              'inline-flex items-center gap-1.5 px-3 py-1.5 text-sm font-medium rounded-md transition-all',
              isActive
                ? 'bg-white text-primary-600 shadow-sm'
                : 'text-gray-500 hover:text-gray-700 hover:bg-white/50',
            )}
            title={m.description}
          >
            <Icon className="w-4 h-4" />
            <span>{m.label}</span>
          </button>
        );
      })}
    </div>
  );
}
