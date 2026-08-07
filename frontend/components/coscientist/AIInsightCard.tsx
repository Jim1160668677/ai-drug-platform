'use client';

/**
 * AIInsightCard — 列表内 AI 建议卡片
 *
 * 单条洞察的展示与操作单元，用于 InsightsCenter 与其他列表场景。
 * - 展示标题/摘要/置信度/类型标签
 * - 操作：采纳（acceptInsight）/ 忽略（dismissInsight）/ 详情展开
 * - 按 insight_type 用渐变左边框区分（drug_repurposing=紫、optimization=蓝、mechanism=绿 …）
 * - 采纳后显示绿色「已采纳」状态徽章
 */
import { useState } from 'react';
import { useMutation, useQueryClient } from '@tanstack/react-query';
import { acceptInsight, dismissInsight, type Insight } from '@/lib/api';
import { toast } from '@/lib/notification';
import { Check, X, ChevronDown, ChevronUp, Sparkles, CheckCircle2 } from 'lucide-react';

interface AIInsightCardProps {
  insight: Insight;
  /** 采纳成功后回调，回传 accepted_entity_id（如有） */
  onAccepted?: (entityId: string) => void;
}

/** insight_type → 视觉样式映射（左边框 + 标签） */
const TYPE_STYLES: Record<string, { border: string; badge: string; label: string }> = {
  drug_repurposing: { border: 'border-l-purple-500', badge: 'bg-purple-100 text-purple-700', label: '药物重定位' },
  optimization: { border: 'border-l-blue-500', badge: 'bg-blue-100 text-blue-700', label: '优化建议' },
  mechanism: { border: 'border-l-green-500', badge: 'bg-green-100 text-green-700', label: '机制洞察' },
  target: { border: 'border-l-amber-500', badge: 'bg-amber-100 text-amber-700', label: '靶点发现' },
  hypothesis: { border: 'border-l-pink-500', badge: 'bg-pink-100 text-pink-700', label: '假设生成' },
  risk: { border: 'border-l-red-500', badge: 'bg-red-100 text-red-700', label: '风险提示' },
};

function getTypeStyle(insightType: string) {
  return TYPE_STYLES[insightType] ?? { border: 'border-l-indigo-500', badge: 'bg-indigo-100 text-indigo-700', label: insightType };
}

/** 置信度 → 颜色 */
function confidenceColor(score: number | null): string {
  if (score == null) return 'text-gray-400';
  if (score >= 0.75) return 'text-green-600';
  if (score >= 0.5) return 'text-amber-600';
  return 'text-red-500';
}

export default function AIInsightCard({ insight, onAccepted }: AIInsightCardProps) {
  const queryClient = useQueryClient();
  const [expanded, setExpanded] = useState(false);

  const style = getTypeStyle(insight.insight_type);
  const isAccepted = insight.status === 'accepted';
  const isDismissed = insight.status === 'dismissed';
  const isInactive = isAccepted || isDismissed;

  const acceptMutation = useMutation({
    mutationFn: () => acceptInsight(insight.id),
    onSuccess: (res: unknown) => {
      const acceptedId =
        (res && typeof res === 'object' && 'accepted_entity_id' in res
          ? (res as { accepted_entity_id?: string }).accepted_entity_id
          : insight.accepted_entity_id) ?? insight.id;
      toast.success('已采纳洞察', '已生成对应实体，可在工作台查看');
      queryClient.invalidateQueries({ queryKey: ['coscientist-insights'] });
      queryClient.invalidateQueries({ queryKey: ['coscientist-pending-count'] });
      onAccepted?.(acceptedId ?? '');
    },
    onError: (err: unknown) => {
      const msg = err instanceof Error ? err.message : '请稍后重试';
      toast.error('采纳失败', msg);
    },
  });

  const dismissMutation = useMutation({
    mutationFn: () => dismissInsight(insight.id),
    onSuccess: () => {
      toast.info('已忽略该洞察');
      queryClient.invalidateQueries({ queryKey: ['coscientist-insights'] });
      queryClient.invalidateQueries({ queryKey: ['coscientist-pending-count'] });
    },
    onError: (err: unknown) => {
      const msg = err instanceof Error ? err.message : '请稍后重试';
      toast.error('操作失败', msg);
    },
  });

  const hasDetails = !!insight.details && Object.keys(insight.details).length > 0;

  return (
    <div
      className={`bg-white border border-gray-200 border-l-4 ${style.border} rounded-r-lg rounded-l-sm p-3 transition-opacity ${
        isInactive ? 'opacity-60' : ''
      }`}
    >
      {/* 头部：类型标签 + 标题 */}
      <div className="flex items-start justify-between gap-2 mb-1.5">
        <div className="flex items-center gap-2 min-w-0 flex-1">
          <Sparkles className="w-3.5 h-3.5 text-indigo-400 flex-shrink-0" />
          <span className={`text-[10px] px-1.5 py-0.5 rounded font-medium flex-shrink-0 ${style.badge}`}>
            {style.label}
          </span>
          {insight.confidence_score != null && (
            <span className={`text-[10px] font-medium flex-shrink-0 ${confidenceColor(insight.confidence_score)}`}>
              置信度 {Math.round(insight.confidence_score * 100)}%
            </span>
          )}
        </div>
        {isAccepted && (
          <span className="inline-flex items-center gap-1 text-[10px] text-green-700 bg-green-50 px-1.5 py-0.5 rounded flex-shrink-0">
            <CheckCircle2 className="w-3 h-3" />
            已采纳
          </span>
        )}
        {isDismissed && (
          <span className="text-[10px] text-gray-400 flex-shrink-0">已忽略</span>
        )}
      </div>

      {/* 标题与摘要 */}
      <h4 className="text-sm font-semibold text-gray-800 mb-1 leading-snug">{insight.title}</h4>
      <p className="text-xs text-gray-600 leading-relaxed line-clamp-3">{insight.summary}</p>

      {/* 详情展开 */}
      {hasDetails && (
        <div className="mt-1">
          <button
            type="button"
            onClick={() => setExpanded((v) => !v)}
            className="inline-flex items-center gap-1 text-[11px] text-indigo-500 hover:text-indigo-700"
          >
            {expanded ? <ChevronUp className="w-3 h-3" /> : <ChevronDown className="w-3 h-3" />}
            {expanded ? '收起详情' : '查看详情'}
          </button>
          {expanded && (
            <pre className="mt-1.5 p-2 bg-gray-50 rounded text-[11px] text-gray-600 overflow-x-auto whitespace-pre-wrap break-words max-h-48 overflow-y-auto">
              {JSON.stringify(insight.details, null, 2)}
            </pre>
          )}
        </div>
      )}

      {/* 建议动作 */}
      {insight.suggested_action && !isInactive && (
        <div className="mt-2 text-[11px] text-gray-500 italic">
          建议：{insight.suggested_action}
        </div>
      )}

      {/* 操作按钮 */}
      {!isInactive && (
        <div className="flex items-center gap-2 mt-2.5">
          <button
            type="button"
            onClick={() => acceptMutation.mutate()}
            disabled={acceptMutation.isPending}
            className="inline-flex items-center gap-1 px-2.5 py-1 text-xs font-medium text-white bg-indigo-600 hover:bg-indigo-700 rounded transition-colors disabled:opacity-50"
          >
            <Check className="w-3 h-3" />
            {acceptMutation.isPending ? '采纳中…' : '采纳'}
          </button>
          <button
            type="button"
            onClick={() => dismissMutation.mutate()}
            disabled={dismissMutation.isPending}
            className="inline-flex items-center gap-1 px-2.5 py-1 text-xs text-gray-500 hover:text-gray-700 hover:bg-gray-100 rounded transition-colors disabled:opacity-50"
          >
            <X className="w-3 h-3" />
            忽略
          </button>
        </div>
      )}
    </div>
  );
}
