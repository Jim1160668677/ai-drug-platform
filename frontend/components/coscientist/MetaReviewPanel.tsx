'use client';

import { useQuery } from '@tanstack/react-query';
import { getMetaReview } from '@/lib/api';
import { Loader2, FileText, DollarSign, Clock, CheckCircle } from 'lucide-react';

export default function MetaReviewPanel({ runId }: { runId: string }) {
  const { data, isLoading, isError } = useQuery({
    queryKey: ['coscientist-meta-review', runId],
    queryFn: () => getMetaReview(runId),
    enabled: !!runId,
    retry: false,
  });

  if (isLoading) {
    return (
      <div className="flex items-center justify-center py-8">
        <Loader2 className="w-5 h-5 animate-spin text-gray-400" />
      </div>
    );
  }

  if (isError || !data) {
    return (
      <div className="text-center py-8 text-gray-400 text-sm">
        <FileText className="w-8 h-8 mx-auto mb-2 opacity-40" />
        Meta-review 尚未生成 — 运行完成后在最终阶段产出
      </div>
    );
  }

  return (
    <div className="space-y-3">
      <div className="flex items-center gap-2 mb-2">
        <FileText className="w-4 h-4 text-indigo-500" />
        <h3 className="text-sm font-semibold text-gray-700">Meta-review 综合报告</h3>
        <CheckCircle className="w-4 h-4 text-green-500" />
      </div>

      {/* 指标 */}
      <div className="grid grid-cols-2 gap-2">
        {data.total_cost_usd != null && (
          <div className="p-2 bg-amber-50 border border-amber-200 rounded-lg flex items-center gap-2">
            <DollarSign className="w-4 h-4 text-amber-500" />
            <div>
              <div className="text-xs text-gray-500">总成本</div>
              <div className="text-sm font-medium">${data.total_cost_usd.toFixed(4)}</div>
            </div>
          </div>
        )}
        {data.duration_sec != null && (
          <div className="p-2 bg-blue-50 border border-blue-200 rounded-lg flex items-center gap-2">
            <Clock className="w-4 h-4 text-blue-500" />
            <div>
              <div className="text-xs text-gray-500">总时长</div>
              <div className="text-sm font-medium">{data.duration_sec.toFixed(1)}s</div>
            </div>
          </div>
        )}
      </div>

      {/* 报告正文 */}
      <div className="p-4 bg-white border border-gray-200 rounded-lg">
        <div className="text-xs font-medium text-gray-400 mb-2">综合评审报告</div>
        <div className="prose prose-sm max-w-none">
          <p className="text-sm text-gray-700 whitespace-pre-wrap leading-relaxed">{data.meta_review}</p>
        </div>
      </div>

      {/* 最终排名摘要 */}
      {data.final_rankings && (
        <div className="p-4 bg-indigo-50 border border-indigo-200 rounded-lg">
          <div className="text-xs font-medium text-indigo-700 mb-2">最终排名摘要</div>
          <pre className="text-xs text-gray-600 overflow-x-auto">
            {JSON.stringify(data.final_rankings, null, 2)}
          </pre>
        </div>
      )}

      {data.completed_at && (
        <div className="text-xs text-gray-400 text-center">
          完成时间: {new Date(data.completed_at).toLocaleString('zh-CN')}
        </div>
      )}
    </div>
  );
}
