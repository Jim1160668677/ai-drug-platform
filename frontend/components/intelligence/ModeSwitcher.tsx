'use client';

/**
 * ModeSwitcher — 模式切换器（组件 3/18）
 *
 * 五模式 segmented control：chat / reasoning / agent / hybrid / auto
 * 切换后调用 force-mode 端点并 toast 提示。
 *
 * 端点：POST /intelligence/sessions/{id}/force-mode
 */
import { useMutation, useQueryClient } from '@tanstack/react-query';
import clsx from 'clsx';
import { MessageCircle, Brain, Bot, Layers, Sparkles } from 'lucide-react';
import { forceMode } from '@/lib/api';
import { toast } from '@/lib/notification';
import type { PrimaryMode, IntentInfo } from '@/types/intelligence';

interface ModeSwitcherProps {
  sessionId: string;
  currentMode: PrimaryMode | string;
  intent?: IntentInfo | null;
  onModeChanged?: (mode: string) => void;
}

const MODES: Array<{
  value: PrimaryMode;
  label: string;
  icon: typeof MessageCircle;
}> = [
  { value: 'chat', label: '问答', icon: MessageCircle },
  { value: 'reasoning', label: '推理', icon: Brain },
  { value: 'agent', label: 'Agent', icon: Bot },
  { value: 'hybrid', label: '混合', icon: Layers },
  { value: 'auto', label: '自动', icon: Sparkles },
];

export default function ModeSwitcher({
  sessionId,
  currentMode,
  intent,
  onModeChanged,
}: ModeSwitcherProps) {
  const queryClient = useQueryClient();

  const mutation = useMutation({
    mutationFn: (mode: PrimaryMode) => forceMode(sessionId, mode),
    onSuccess: (data) => {
      queryClient.invalidateQueries({ queryKey: ['intelligence-session', sessionId] });
      onModeChanged?.(data.primary_mode);
      toast.success(`已切换到${MODES.find((m) => m.value === data.primary_mode)?.label ?? data.primary_mode}模式`);
    },
    onError: () => toast.error('模式切换失败'),
  });

  return (
    <div className="flex items-center gap-2">
      {/* 模式按钮组 */}
      <div className="inline-flex items-center gap-0.5 p-0.5 bg-gray-100 rounded-lg">
        {MODES.map((mode) => {
          const Icon = mode.icon;
          const isActive = currentMode === mode.value;
          return (
            <button
              key={mode.value}
              disabled={mutation.isPending}
              onClick={() => mutation.mutate(mode.value)}
              className={clsx(
                'inline-flex items-center gap-1 px-2.5 py-1 text-xs font-medium rounded-md transition-colors',
                isActive
                  ? 'bg-white text-primary-600 shadow-sm'
                  : 'text-gray-500 hover:text-gray-700',
              )}
              title={mode.label}
            >
              <Icon className="w-3.5 h-3.5" />
              <span className="hidden sm:inline">{mode.label}</span>
            </button>
          );
        })}
      </div>

      {/* 意图信息 */}
      {intent && intent.mode && (
        <div className="flex items-center gap-1 text-xs text-gray-400">
          <span>路由:</span>
          <span className="font-medium text-gray-600">{intent.mode}</span>
          {typeof intent.confidence === 'number' && (
            <span className="text-gray-400">
              ({(intent.confidence * 100).toFixed(0)}%)
            </span>
          )}
        </div>
      )}
    </div>
  );
}
