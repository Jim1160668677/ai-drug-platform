'use client';

import { useState, useMemo } from 'react';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { listRuns, deleteRun } from '@/lib/api';
import { toast } from '@/lib/notification';
import type { RunResponse, RunStatus } from '@/types/coscientist';
import { Clock, CheckCircle, XCircle, Play, AlertCircle, Trash2, Loader2, RefreshCw, Inbox } from 'lucide-react';
import EmptyState from '@/components/ui/EmptyState';
import { SkeletonList } from '@/components/ui/Skeleton';

const STATUS_CONFIG: Record<string, { icon: typeof Clock; color: string; label: string }> = {
  pending: { icon: Clock, color: 'text-gray-500 bg-gray-100', label: '待执行' },
  running: { icon: Play, color: 'text-blue-600 bg-blue-100', label: '运行中' },
  awaiting_feedback: { icon: AlertCircle, color: 'text-amber-600 bg-amber-100', label: '等待反馈' },
  completed: { icon: CheckCircle, color: 'text-green-600 bg-green-100', label: '已完成' },
  failed: { icon: XCircle, color: 'text-red-600 bg-red-100', label: '失败' },
  cancelled: { icon: XCircle, color: 'text-gray-500 bg-gray-100', label: '已取消' },
};

// 活跃状态（需要轮询刷新）
const ACTIVE_STATUSES = new Set(['pending', 'running', 'awaiting_feedback']);

interface RunListProps {
  selectedRunId?: string;
  onSelect?: (runId: string) => void;
  refreshKey?: number;
}

export default function RunList({ selectedRunId, onSelect, refreshKey = 0 }: RunListProps) {
  const queryClient = useQueryClient();
  const [confirmingId, setConfirmingId] = useState<string | null>(null);

  const { data, isLoading, isError, refetch, isFetching } = useQuery({
    queryKey: ['coscientist-runs', refreshKey],
    queryFn: () => listRuns({ page: 1, page_size: 20 }),
    // 智能轮询：仅当存在活跃运行时才每 5 秒刷新
    refetchInterval: (query) => {
      const items = query.state.data?.items ?? [];
      const hasActive = items.some((r: RunResponse) => ACTIVE_STATUSES.has(r.status));
      return hasActive ? 5000 : false;
    },
  });

  const runs: RunResponse[] = data?.items ?? [];

  // 是否有活跃运行（用于决定是否显示实时刷新指示）
  const hasActiveRun = useMemo(
    () => runs.some((r) => ACTIVE_STATUSES.has(r.status)),
    [runs],
  );

  const deleteMutation = useMutation({
    mutationFn: (runId: string) => deleteRun(runId),
    onSuccess: (_data, runId) => {
      queryClient.invalidateQueries({ queryKey: ['coscientist-runs'] });
      if (runId === selectedRunId) {
        onSelect?.('');
      }
      setConfirmingId(null);
      toast.success('删除成功', '运行记录已删除，关联假设已保留');
    },
    onError: (err: any, runId) => {
      setConfirmingId(null);
      const msg = err?.response?.data?.error?.message ?? err?.message ?? '未知错误';
      toast.error('删除失败', msg);
    },
  });

  const handleDelete = (e: React.MouseEvent, runId: string) => {
    e.stopPropagation();
    if (confirmingId === runId) {
      deleteMutation.mutate(runId);
    } else {
      setConfirmingId(runId);
    }
  };

  const handleCancelDelete = (e: React.MouseEvent) => {
    e.stopPropagation();
    setConfirmingId(null);
  };

  if (isLoading) {
    return <SkeletonList count={3} />;
  }

  if (isError) {
    return (
      <div className="flex flex-col items-center justify-center py-8 px-4 text-center">
        <XCircle className="w-8 h-8 text-red-400 mb-2" />
        <p className="text-sm text-gray-600 mb-3">运行列表加载失败</p>
        <button
          onClick={() => refetch()}
          className="inline-flex items-center gap-1.5 px-3 py-1.5 text-xs font-medium text-indigo-600 border border-indigo-200 rounded-lg hover:bg-indigo-50 transition"
        >
          <RefreshCw className="w-3.5 h-3.5" />
          重新加载
        </button>
      </div>
    );
  }

  if (runs.length === 0) {
    return (
      <EmptyState
        type="no-data"
        title="暂无运行记录"
        description="在左侧创建第一个 Co-Scientist 运行"
        iconSize="sm"
      />
    );
  }

  return (
    <div className="space-y-2">
      {/* 实时刷新指示 */}
      {hasActiveRun && (
        <div className="flex items-center justify-between px-1 py-1 text-xs text-blue-500">
          <span className="inline-flex items-center gap-1">
            <span className="relative flex h-2 w-2">
              <span className="animate-ping absolute inline-flex h-full w-full rounded-full bg-blue-400 opacity-75" />
              <span className="relative inline-flex rounded-full h-2 w-2 bg-blue-500" />
            </span>
            实时同步运行进度
          </span>
          {isFetching && <Loader2 className="w-3 h-3 animate-spin" />}
        </div>
      )}

      {runs.map((run) => {
        const cfg = STATUS_CONFIG[run.status] ?? STATUS_CONFIG.pending;
        const Icon = cfg.icon;
        const isSelected = run.id === selectedRunId;
        const isConfirming = confirmingId === run.id;
        const isDeleting = deleteMutation.isPending && deleteMutation.variables === run.id;
        return (
          <div
            key={run.id}
            className={`group relative w-full p-3 pr-9 rounded-lg border transition ${
              isSelected
                ? 'border-indigo-500 bg-indigo-50'
                : isConfirming
                ? 'border-red-300 bg-red-50'
                : 'border-gray-200 hover:border-gray-300 bg-white'
            }`}
          >
            <button
              onClick={() => onSelect?.(run.id)}
              className="w-full text-left"
            >
              <div className="flex items-center justify-between mb-1">
                <span className={`inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-xs font-medium ${cfg.color}`}>
                  <Icon className={`w-3 h-3 ${run.status === 'running' ? 'animate-pulse' : ''}`} />
                  {cfg.label}
                </span>
                <span className="text-xs text-gray-400">
                  轮次 {run.current_round}/{run.max_rounds}
                </span>
              </div>
              <p className="text-sm text-gray-700 line-clamp-2">{run.research_goal}</p>
              <div className="flex items-center gap-3 mt-1 text-xs text-gray-400">
                {run.case_type && run.case_type !== 'custom' && (
                  <span className="px-1.5 py-0.5 bg-gray-100 rounded text-gray-500">{run.case_type}</span>
                )}
                {run.current_phase && <span>阶段: {run.current_phase}</span>}
                {run.total_cost_usd != null && <span>成本: ${run.total_cost_usd.toFixed(4)}</span>}
                {run.duration_sec != null && <span>耗时: {Math.round(run.duration_sec)}s</span>}
              </div>
            </button>

            {/* 删除按钮 */}
            <button
              onClick={(e) => handleDelete(e, run.id)}
              disabled={isDeleting}
              className={`absolute top-2.5 right-2 p-1 rounded transition ${
                isConfirming
                  ? 'bg-red-500 text-white hover:bg-red-600'
                  : 'text-gray-300 hover:text-red-500 hover:bg-red-50 opacity-0 group-hover:opacity-100'
              } ${isDeleting ? 'opacity-50 cursor-not-allowed' : ''}`}
              title={isConfirming ? '再次点击确认删除' : '删除运行'}
              style={{ opacity: isConfirming || isDeleting ? 1 : undefined }}
            >
              {isDeleting ? (
                <Loader2 className="w-3.5 h-3.5 animate-spin" />
              ) : (
                <Trash2 className="w-3.5 h-3.5" />
              )}
            </button>

            {/* 确认删除提示 */}
            {isConfirming && !isDeleting && (
              <div className="mt-1.5 flex items-center justify-end gap-2 text-xs">
                <span className="text-red-500">确认删除？关联假设将保留</span>
                <button
                  onClick={handleCancelDelete}
                  className="px-2 py-0.5 text-gray-500 border border-gray-200 rounded hover:bg-gray-50"
                >
                  取消
                </button>
              </div>
            )}
          </div>
        );
      })}
    </div>
  );
}
