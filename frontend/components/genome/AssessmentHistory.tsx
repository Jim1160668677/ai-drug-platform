'use client';

import { useQuery } from '@tanstack/react-query';
import { History, X } from 'lucide-react';
import { listAssessments } from '@/lib/api';
import Badge from '@/components/ui/Badge';
import Loading from '@/components/ui/Loading';

interface AssessmentHistoryProps {
  genomeId: string | null;
  /** 选中历史评估时回调 */
  onSelect?: (assessment: any) => void;
  /** 是否以抽屉模式显示 */
  open?: boolean;
  onClose?: () => void;
}

const RISK_LABEL: Record<string, string> = {
  LOW: '低风险',
  MODERATE: '中等风险',
  HIGH: '高风险',
  VERY_HIGH: '极高风险',
};

const RISK_COLOR: Record<string, any> = {
  LOW: 'green',
  MODERATE: 'yellow',
  HIGH: 'orange' as any,
  VERY_HIGH: 'red',
};

export default function AssessmentHistory({
  genomeId,
  onSelect,
  open,
  onClose,
}: AssessmentHistoryProps) {
  const { data, isLoading } = useQuery({
    queryKey: ['genome-assessments', genomeId],
    queryFn: () => listAssessments(genomeId!),
    enabled: !!genomeId,
  });

  const assessments: any[] = data?.data?.assessments ?? data?.assessments ?? [];

  const content = (
    <div className="space-y-2">
      <div className="flex items-center justify-between mb-2">
        <div className="flex items-center gap-2">
          <History className="w-4 h-4 text-gray-600" />
          <span className="text-sm font-semibold">历史评估</span>
        </div>
        {open && onClose && (
          <button onClick={onClose} className="text-gray-400 hover:text-gray-600">
            <X className="w-4 h-4" />
          </button>
        )}
      </div>

      {isLoading ? (
        <Loading size="sm" label="加载历史评估..." />
      ) : !assessments || assessments.length === 0 ? (
        <div className="rounded-lg border border-dashed border-gray-300 bg-gray-50 p-6 text-center text-xs text-gray-500">
          暂无历史评估
        </div>
      ) : (
        assessments.map((a: any) => (
          <div
            key={a.id}
            className="rounded-lg border border-gray-200 bg-white p-3 cursor-pointer hover:border-primary-300 hover:bg-primary-50/50 transition-colors"
            onClick={() => onSelect?.(a)}
          >
            <div className="flex items-center justify-between mb-1">
              <Badge
                variant={RISK_COLOR[a.risk_level] || 'gray'}
                value={RISK_LABEL[a.risk_level] || a.risk_level || '—'}
              />
              <span className="text-xs text-gray-400">
                {a.created_at ? new Date(a.created_at).toLocaleString('zh-CN') : ''}
              </span>
            </div>
            <div className="flex items-center justify-between text-xs text-gray-600">
              <span>
                核心位点：<strong>{a.core_loci_matched ?? 0}</strong>
              </span>
              <span>
                辅助位点：<strong>{a.auxiliary_loci_matched ?? 0}</strong>
              </span>
              <span>
                风险评分：
                <strong className="ml-1 text-primary-600">
                  {((a.overall_risk_score ?? 0) * 100).toFixed(1)}%
                </strong>
              </span>
            </div>
          </div>
        ))
      )}
    </div>
  );

  if (open) {
    return (
      <div className="fixed inset-0 z-50 flex justify-end bg-black/30">
        <div className="bg-white w-96 h-full p-5 shadow-xl overflow-y-auto">
          {content}
        </div>
      </div>
    );
  }

  return content;
}
