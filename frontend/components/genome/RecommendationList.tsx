'use client';

import { AlertCircle, CheckCircle, Info, AlertTriangle } from 'lucide-react';

interface RecommendationItem {
  id?: string;
  category?: string;
  content: string;
  priority?: 'urgent' | 'high' | 'medium' | 'low' | string;
  evidence?: string;
}

interface RecommendationListProps {
  recommendations: RecommendationItem[];
  loading?: boolean;
}

const PRIORITY_CONFIG: Record<
  string,
  { label: string; color: string; bg: string; border: string; icon: typeof AlertCircle }
> = {
  urgent: {
    label: '紧急',
    color: 'text-red-700',
    bg: 'bg-red-50',
    border: 'border-red-200',
    icon: AlertCircle,
  },
  high: {
    label: '高',
    color: 'text-orange-700',
    bg: 'bg-orange-50',
    border: 'border-orange-200',
    icon: AlertTriangle,
  },
  medium: {
    label: '中',
    color: 'text-yellow-700',
    bg: 'bg-yellow-50',
    border: 'border-yellow-200',
    icon: Info,
  },
  low: {
    label: '低',
    color: 'text-gray-700',
    bg: 'bg-gray-50',
    border: 'border-gray-200',
    icon: CheckCircle,
  },
};

export default function RecommendationList({
  recommendations,
  loading,
}: RecommendationListProps) {
  if (loading) {
    return (
      <div className="space-y-2">
        {[1, 2, 3].map((i) => (
          <div key={i} className="h-16 animate-pulse rounded-lg bg-gray-100" />
        ))}
      </div>
    );
  }

  if (!recommendations || recommendations.length === 0) {
    return (
      <div className="rounded-lg border border-dashed border-gray-300 bg-gray-50 p-6 text-center text-sm text-gray-500">
        暂无生活建议
      </div>
    );
  }

  // 按优先级排序：urgent > high > medium > low
  const priorityOrder = ['urgent', 'high', 'medium', 'low'];
  const sorted = [...recommendations].sort((a, b) => {
    const ai = priorityOrder.indexOf(a.priority || 'low');
    const bi = priorityOrder.indexOf(b.priority || 'low');
    return (ai === -1 ? 99 : ai) - (bi === -1 ? 99 : bi);
  });

  return (
    <div className="space-y-2">
      {sorted.map((r, idx) => {
        const cfg = PRIORITY_CONFIG[r.priority || 'low'] || PRIORITY_CONFIG.low;
        const Icon = cfg.icon;
        return (
          <div
            key={r.id || idx}
            className={`flex items-start gap-3 rounded-lg border p-3 ${cfg.bg} ${cfg.border}`}
          >
            <Icon className={`w-5 h-5 shrink-0 mt-0.5 ${cfg.color}`} />
            <div className="flex-1 min-w-0">
              <div className="flex items-center gap-2 mb-1">
                <span
                  className={`text-xs font-bold uppercase px-1.5 py-0.5 rounded ${cfg.color} ${cfg.bg} ${cfg.border} border`}
                >
                  {cfg.label}
                </span>
                {r.category && (
                  <span className="text-xs text-gray-500">{r.category}</span>
                )}
              </div>
              <div className="text-sm text-gray-800 whitespace-pre-wrap">
                {r.content}
              </div>
              {r.evidence && (
                <div className="mt-1 text-xs text-gray-500 italic">
                  依据：{r.evidence}
                </div>
              )}
            </div>
          </div>
        );
      })}
    </div>
  );
}
