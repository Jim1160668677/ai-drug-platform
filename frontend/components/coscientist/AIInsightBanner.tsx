'use client';

/**
 * AIInsightBanner — 业务页面顶部洞察提示条
 *
 * 在靶点/分子/实验/治疗等业务页面顶部嵌入，展示该实体相关的 AI 待处理洞察数量。
 * - 无待处理洞察时返回 null（不占位）
 * - 「查看全部」打开 Co-Scientist 浮窗（setCopilotOpen(true)）
 * - 「稍后」批量标记该实体类型的洞察为已读（bulkMarkInsightsRead）
 */
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { listInsights, bulkMarkInsightsRead } from '@/lib/api';
import { useAppStore } from '@/lib/store';
import { toast } from '@/lib/notification';
import { Sparkles, ChevronRight, Clock } from 'lucide-react';

interface AIInsightBannerProps {
  /** 实体类型：target / molecule / experiment / treatment / hypothesis ... */
  entityType: string;
  /** 实体 ID（可选，未传则按 entity_type 聚合） */
  entityId?: string;
  /** 项目 ID（可选，缺省从 useAppStore.currentProject 取） */
  projectId?: string;
}

export default function AIInsightBanner({ entityType, entityId, projectId }: AIInsightBannerProps) {
  const queryClient = useQueryClient();
  const setCopilotOpen = useAppStore((s) => s.setCopilotOpen);
  const storeProjectId = useAppStore((s) => s.currentProject?.id);
  const effectiveProjectId = projectId ?? storeProjectId;

  const queryKey = [
    'coscientist-insights',
    'banner',
    entityType,
    entityId ?? 'all',
    effectiveProjectId ?? 'no-project',
  ];

  const { data } = useQuery({
    queryKey,
    queryFn: () =>
      listInsights({
        entity_type: entityType,
        entity_id: entityId,
        project_id: effectiveProjectId,
        status: 'pending',
        page_size: 100,
      }),
    enabled: !!entityType,
    refetchInterval: 30000, // 30 秒轮询，保持新鲜度
  });

  const laterMutation = useMutation({
    mutationFn: () =>
      bulkMarkInsightsRead({ entity_type: entityType, project_id: effectiveProjectId }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['coscientist-insights'] });
      queryClient.invalidateQueries({ queryKey: ['coscientist-pending-count'] });
      toast.success('已稍后提醒', '相关洞察已标记为已读');
    },
    onError: (err: unknown) => {
      const msg = err instanceof Error ? err.message : '请稍后重试';
      toast.error('操作失败', msg);
    },
  });

  const pendingCount = data?.items?.length ?? 0;
  if (pendingCount === 0) return null;

  return (
    <div className="flex items-center justify-between gap-3 px-4 py-2.5 bg-gradient-to-r from-blue-50 to-indigo-50 border border-blue-200 rounded-lg">
      <div className="flex items-center gap-2.5 min-w-0">
        <Sparkles className="w-4 h-4 text-blue-500 animate-pulse flex-shrink-0" />
        <span className="text-sm text-blue-800 truncate">
          <span aria-hidden>✨</span> AI 发现 <strong className="font-semibold">{pendingCount}</strong> 个新洞察
        </span>
      </div>
      <div className="flex items-center gap-1 flex-shrink-0">
        <button
          type="button"
          onClick={() => setCopilotOpen(true)}
          className="inline-flex items-center gap-1 px-2.5 py-1 text-xs font-medium text-blue-700 hover:text-blue-800 hover:bg-blue-100 rounded transition-colors"
        >
          查看全部
          <ChevronRight className="w-3 h-3" />
        </button>
        <button
          type="button"
          onClick={() => laterMutation.mutate()}
          disabled={laterMutation.isPending}
          className="inline-flex items-center gap-1 px-2.5 py-1 text-xs text-gray-500 hover:text-gray-700 hover:bg-white/60 rounded transition-colors disabled:opacity-50"
        >
          <Clock className="w-3 h-3" />
          稍后
        </button>
      </div>
    </div>
  );
}
