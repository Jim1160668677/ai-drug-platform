'use client';

import { Bot, Square, Coins, Clock, Zap, WifiOff, Loader2 } from 'lucide-react';
import clsx from 'clsx';
import Button from '@/components/ui/Button';
import type { TaskStatus } from '@/types/agent';

export type WSStatus = 'connected' | 'connecting' | 'reconnecting' | 'disconnected';

interface AgentHeaderProps {
  title: string;
  taskStatus?: TaskStatus;
  currentTaskId?: string | null;
  tokenUsage?: { prompt: number; completion: number; total: number };
  costUsd?: number;
  durationSec?: number;
  isRunning: boolean;
  onCancel: () => void;
  /**
   * WebSocket 连接状态
   * 设计来源：2026-07-18-agent-functional-design.md §4.4
   */
  wsStatus?: WSStatus;
}

const STATUS_LABELS: Record<TaskStatus, string> = {
  pending: '排队中',
  planning: '规划中',
  running: '执行中',
  awaiting_confirmation: '等待确认',
  completed: '已完成',
  failed: '失败',
  cancelled: '已取消',
};

const STATUS_STYLES: Record<TaskStatus, string> = {
  pending: 'bg-gray-100 text-gray-700',
  planning: 'bg-blue-100 text-blue-700',
  running: 'bg-blue-100 text-blue-700 animate-pulse',
  awaiting_confirmation: 'bg-yellow-100 text-yellow-800',
  completed: 'bg-green-100 text-green-800',
  failed: 'bg-red-100 text-red-800',
  cancelled: 'bg-gray-100 text-gray-600',
};

const WS_LABELS: Record<WSStatus, string> = {
  connected: '已连接',
  connecting: '连接中',
  reconnecting: '重连中',
  disconnected: '已断开',
};

const WS_DOT_STYLES: Record<WSStatus, string> = {
  connected: 'bg-green-500',
  connecting: 'bg-yellow-500 animate-pulse',
  reconnecting: 'bg-yellow-500 animate-pulse',
  disconnected: 'bg-red-500',
};

export function AgentHeader({
  title,
  taskStatus,
  currentTaskId,
  tokenUsage,
  costUsd,
  durationSec,
  isRunning,
  onCancel,
  wsStatus = 'connected',
}: AgentHeaderProps) {
  const wsDisconnected = wsStatus === 'disconnected';
  const wsReconnecting = wsStatus === 'reconnecting' || wsStatus === 'connecting';

  return (
    <div className="border-b border-gray-200 bg-white">
      <div className="flex items-center justify-between px-4 py-3">
        <div className="flex items-center gap-3 min-w-0">
          <div className="w-8 h-8 rounded-lg bg-primary-50 flex items-center justify-center shrink-0">
            <Bot className="w-5 h-5 text-primary-600" />
          </div>
          <div className="min-w-0">
            <div className="text-sm font-semibold text-gray-900 truncate">{title}</div>
            <div className="flex items-center gap-2 text-xs text-gray-500">
              {taskStatus && (
                <span
                  className={clsx(
                    'inline-flex items-center px-1.5 py-0.5 rounded font-medium',
                    STATUS_STYLES[taskStatus]
                  )}
                >
                  {STATUS_LABELS[taskStatus]}
                </span>
              )}
              {currentTaskId && (
                <span className="font-mono text-[10px] text-gray-400">
                  #{currentTaskId.slice(0, 8)}
                </span>
              )}
              {/* WebSocket 状态指示器 */}
              {wsStatus && (
                <span
                  className={clsx(
                    'inline-flex items-center gap-1 px-1.5 py-0.5 rounded font-medium',
                    wsDisconnected
                      ? 'bg-red-50 text-red-700'
                      : wsReconnecting
                        ? 'bg-yellow-50 text-yellow-700'
                        : 'bg-gray-50 text-gray-500'
                  )}
                  title={`WebSocket：${WS_LABELS[wsStatus]}`}
                >
                  <span className={clsx('w-1.5 h-1.5 rounded-full', WS_DOT_STYLES[wsStatus])} />
                  {WS_LABELS[wsStatus]}
                </span>
              )}
            </div>
          </div>
        </div>

        <div className="flex items-center gap-3">
          {tokenUsage && tokenUsage.total > 0 && (
            <div className="flex items-center gap-1 text-xs text-gray-600" title="Token 用量">
              <Zap className="w-3 h-3" />
              <span>{tokenUsage.total.toLocaleString()}</span>
            </div>
          )}
          {costUsd != null && costUsd > 0 && (
            <div className="flex items-center gap-1 text-xs text-gray-600" title="成本">
              <Coins className="w-3 h-3" />
              <span>${costUsd.toFixed(4)}</span>
            </div>
          )}
          {durationSec != null && durationSec > 0 && (
            <div className="flex items-center gap-1 text-xs text-gray-600" title="耗时">
              <Clock className="w-3 h-3" />
              <span>{durationSec.toFixed(1)}s</span>
            </div>
          )}
          {isRunning && (
            <Button size="sm" variant="danger" onClick={onCancel}>
              <Square className="w-3 h-3" /> 取消
            </Button>
          )}
        </div>
      </div>

      {/* WebSocket 断连横幅（设计 §4.4：橙色横幅 + 自动重连提示） */}
      {wsDisconnected && (
        <div className="px-4 py-1.5 bg-orange-50 border-t border-orange-200 text-xs text-orange-700 flex items-center gap-2">
          <WifiOff className="w-3 h-3" />
          <span>连接中断，请稍候或刷新页面重试</span>
        </div>
      )}
      {wsReconnecting && (
        <div className="px-4 py-1.5 bg-yellow-50 border-t border-yellow-200 text-xs text-yellow-700 flex items-center gap-2">
          <Loader2 className="w-3 h-3 animate-spin" />
          <span>正在重连...</span>
        </div>
      )}
    </div>
  );
}
