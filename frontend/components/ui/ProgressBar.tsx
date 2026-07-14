/**
 * ProgressBar — 任务进度可视化组件
 *
 * 用于展示异步任务（数据解析、靶点发现、分子设计、联邦训练等）的实时进度。
 *
 * 用法：
 * <ProgressBar progress={progress} />
 * <ProgressBar percent={50} message="处理中" status="running" />
 */
import { CheckCircle, Loader2, XCircle, Clock, AlertTriangle, Square } from 'lucide-react';
import type { TaskProgress } from '@/types/api';
import clsx from 'clsx';

interface ProgressBarProps {
  /** 进度信息（与 percent/message/status 二选一） */
  progress?: TaskProgress | null;
  /** 百分比 0-100（progress 为空时使用） */
  percent?: number;
  /** 进度描述（progress 为空时使用） */
  message?: string;
  /** 状态（progress 为空时使用） */
  status?: 'pending' | 'running' | 'completed' | 'failed' | 'stopped';
  /** 紧凑模式（不显示 message） */
  compact?: boolean;
  className?: string;
}

const STATUS_CONFIG: Record<
  string,
  { label: string; barColor: string; bgColor: string; textColor: string; icon: typeof Clock }
> = {
  pending: {
    label: '待启动',
    barColor: 'bg-gray-400',
    bgColor: 'bg-gray-50',
    textColor: 'text-gray-600',
    icon: Clock,
  },
  running: {
    label: '进行中',
    barColor: 'bg-blue-500',
    bgColor: 'bg-blue-50',
    textColor: 'text-blue-600',
    icon: Loader2,
  },
  completed: {
    label: '已完成',
    barColor: 'bg-green-500',
    bgColor: 'bg-green-50',
    textColor: 'text-green-600',
    icon: CheckCircle,
  },
  failed: {
    label: '失败',
    barColor: 'bg-red-500',
    bgColor: 'bg-red-50',
    textColor: 'text-red-600',
    icon: XCircle,
  },
  stopped: {
    label: '已停止',
    barColor: 'bg-yellow-500',
    bgColor: 'bg-yellow-50',
    textColor: 'text-yellow-600',
    icon: Square,
  },
};

export default function ProgressBar({
  progress,
  percent,
  message,
  status,
  compact = false,
  className,
}: ProgressBarProps) {
  const pct = progress?.percent ?? percent ?? 0;
  const msg = progress?.message ?? message ?? '';
  const st = progress?.status ?? status ?? 'pending';
  const config = STATUS_CONFIG[st] || STATUS_CONFIG.pending;
  const Icon = config.icon;
  const isAnimated = st === 'running';

  return (
    <div className={clsx('rounded-lg p-3', config.bgColor, className)}>
      <div className="flex items-center justify-between mb-1.5">
        <div className="flex items-center gap-1.5">
          <Icon
            className={clsx('w-3.5 h-3.5', config.textColor, isAnimated && 'animate-spin')}
          />
          <span className={clsx('text-xs font-medium', config.textColor)}>
            {config.label}
          </span>
        </div>
        <span className={clsx('text-xs font-bold', config.textColor)}>
          {Math.round(pct)}%
        </span>
      </div>
      <div className="w-full bg-gray-200 rounded-full h-2 overflow-hidden">
        <div
          className={clsx(
            'h-full rounded-full transition-all duration-500',
            config.barColor,
            isAnimated && 'animate-pulse',
          )}
          style={{ width: `${Math.max(0, Math.min(100, pct))}%` }}
        />
      </div>
      {!compact && msg && (
        <div className="mt-1.5 text-xs text-gray-500 truncate" title={msg}>
          {msg}
        </div>
      )}
      {st === 'failed' && !compact && !msg && (
        <div className="mt-1.5 flex items-center gap-1 text-xs text-red-500">
          <AlertTriangle className="w-3 h-3" />
          <span>任务执行失败，请重试或联系管理员</span>
        </div>
      )}
    </div>
  );
}
