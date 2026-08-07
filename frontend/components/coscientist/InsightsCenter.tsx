'use client';

/**
 * InsightsCenter — 浮窗内洞察中心面板
 *
 * 聚合展示当前项目下所有 AI 洞察，支持状态过滤与批量已读。
 * - 用 listInsights({project_id, status, page}) 拉取，按时间倒序
 * - 状态过滤：全部 / 待处理 / 已采纳 / 已忽略
 * - 顶部显示待处理数量徽章 + 「全部已读」按钮（bulkMarkInsightsRead）
 * - 每条洞察用 AIInsightCard 渲染；采纳/忽略后 invalidate 刷新
 */
import { useState } from 'react';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { listInsights, bulkMarkInsightsRead, getPendingInsightCount } from '@/lib/api';
import { useAppStore } from '@/lib/store';
import { toast } from '@/lib/notification';
import AIInsightCard from './AIInsightCard';
import { Loader2, CheckCheck, Inbox, Filter } from 'lucide-react';

interface InsightsCenterProps {
  /** 项目 ID（可选，缺省从 useAppStore.currentProject 取） */
  projectId?: string;
}

type StatusFilter = 'all' | 'pending' | 'accepted' | 'dismissed';

const STATUS_TABS: { key: StatusFilter; label: string }[] = [
  { key: 'all', label: '全部' },
  { key: 'pending', label: '待处理' },
  { key: 'accepted', label: '已采纳' },
  { key: 'dismissed', label: '已忽略' },
];

export default function InsightsCenter({ projectId }: InsightsCenterProps) {
  const queryClient = useQueryClient();
  const storeProjectId = useAppStore((s) => s.currentProject?.id);
  const effectiveProjectId = projectId ?? storeProjectId;
  const [status, setStatus] = useState<StatusFilter>('all');

  const insightsQueryKey = [
    'coscientist-insights',
    'center',
    effectiveProjectId ?? 'no-project',
    status,
  ];

  const { data, isLoading } = useQuery({
    queryKey: insightsQueryKey,
    queryFn: () =>
      listInsights({
        project_id: effectiveProjectId,
        status: status === 'all' ? undefined : status,
        page: 1,
        page_size: 50,
      }),
    enabled: true,
    refetchInterval: 30000,
  });

  // 待处理数量徽章（独立查询，跨过滤状态显示）
  const { data: pendingCountData } = useQuery({
    queryKey: ['coscientist-pending-count', effectiveProjectId ?? 'no-project'],
    queryFn: () => getPendingInsightCount(effectiveProjectId),
    refetchInterval: 30000,
  });

  const readAllMutation = useMutation({
    mutationFn: () => bulkMarkInsightsRead({ project_id: effectiveProjectId }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['coscientist-insights'] });
      queryClient.invalidateQueries({ queryKey: ['coscientist-pending-count'] });
      toast.success('已全部标记为已读');
    },
    onError: (err: unknown) => {
      const msg = err instanceof Error ? err.message : '请稍后重试';
      toast.error('操作失败', msg);
    },
  });

  const items = data?.items ?? [];
  const pendingCount = pendingCountData?.pending_count ?? 0;

  return (
    <div className="flex flex-col h-full">
      {/* 头部：标题 + 待处理徽章 + 全部已读 */}
      <div className="flex items-center justify-between gap-2 px-3 py-2 border-b border-gray-100">
        <div className="flex items-center gap-2 min-w-0">
          <h3 className="text-sm font-semibold text-gray-700">AI 洞察中心</h3>
          {pendingCount > 0 && (
            <span className="inline-flex items-center justify-center min-w-[18px] h-[18px] px-1 text-[10px] font-bold text-white bg-red-500 rounded-full">
              {pendingCount > 99 ? '99+' : pendingCount}
            </span>
          )}
        </div>
        <button
          type="button"
          onClick={() => readAllMutation.mutate()}
          disabled={readAllMutation.isPending || pendingCount === 0}
          className="inline-flex items-center gap-1 px-2 py-1 text-[11px] text-gray-500 hover:text-indigo-600 hover:bg-indigo-50 rounded transition-colors disabled:opacity-40 disabled:cursor-not-allowed"
        >
          <CheckCheck className="w-3 h-3" />
          全部已读
        </button>
      </div>

      {/* 状态过滤标签 */}
      <div className="flex items-center gap-1 px-3 py-2 border-b border-gray-100 overflow-x-auto">
        <Filter className="w-3 h-3 text-gray-400 flex-shrink-0" />
        {STATUS_TABS.map((tab) => (
          <button
            key={tab.key}
            type="button"
            onClick={() => setStatus(tab.key)}
            className={`px-2 py-0.5 text-[11px] rounded whitespace-nowrap transition-colors ${
              status === tab.key
                ? 'bg-indigo-600 text-white'
                : 'text-gray-500 hover:bg-gray-100'
            }`}
          >
            {tab.label}
          </button>
        ))}
      </div>

      {/* 列表区域 */}
      <div className="flex-1 overflow-y-auto p-3 space-y-2">
        {isLoading ? (
          <div className="flex items-center justify-center py-8">
            <Loader2 className="w-5 h-5 animate-spin text-gray-400" />
          </div>
        ) : items.length === 0 ? (
          <div className="flex flex-col items-center justify-center py-10 text-gray-400">
            <Inbox className="w-8 h-8 mb-2" />
            <span className="text-sm">暂无洞察</span>
            <span className="text-xs mt-0.5">AI 推理产出后将在此汇总</span>
          </div>
        ) : (
          items.map((insight) => <AIInsightCard key={insight.id} insight={insight} />)
        )}
      </div>
    </div>
  );
}
