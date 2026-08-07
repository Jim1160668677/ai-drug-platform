'use client';

import { useQuery } from '@tanstack/react-query';
import { getDebates } from '@/lib/api';
import type { DebateLog } from '@/types/coscientist';
import { Loader2, Swords, CheckCircle2, XCircle, Gavel } from 'lucide-react';

export default function DebateViewer({ runId }: { runId: string }) {
  const { data, isLoading } = useQuery({
    queryKey: ['coscientist-debates', runId],
    queryFn: () => getDebates(runId),
    enabled: !!runId,
  });

  if (isLoading) {
    return (
      <div className="flex items-center justify-center py-8">
        <Loader2 className="w-5 h-5 animate-spin text-gray-400" />
      </div>
    );
  }

  const debates: DebateLog[] = data?.debates ?? [];

  if (debates.length === 0) {
    return (
      <div className="text-center py-8 text-gray-400 text-sm">
        暂无辩论日志 — 辩论在 Ranking 阶段后触发
      </div>
    );
  }

  return (
    <div className="space-y-3">
      <div className="flex items-center gap-2 mb-2">
        <Swords className="w-4 h-4 text-red-500" />
        <h3 className="text-sm font-semibold text-gray-700">科学辩论日志（{debates.length} 场）</h3>
      </div>

      {debates.map((debate) => (
        <div key={debate.id} className="p-4 bg-white border border-gray-200 rounded-lg space-y-3">
          <div className="flex items-center justify-between text-xs text-gray-400">
            <span>第 {debate.round_num} 轮辩论</span>
            {debate.consensus_score != null && (
              <span className={`px-2 py-0.5 rounded-full ${
                debate.consensus_score >= 0.7 ? 'bg-green-100 text-green-700' :
                debate.consensus_score >= 0.4 ? 'bg-amber-100 text-amber-700' :
                'bg-red-100 text-red-700'
              }`}>
                共识度: {(debate.consensus_score * 100).toFixed(0)}%
              </span>
            )}
          </div>

          {/* 正方 */}
          <div className="p-3 bg-blue-50 border-l-4 border-blue-400 rounded">
            <div className="flex items-center gap-1 text-xs font-medium text-blue-700 mb-1">
              <CheckCircle2 className="w-3 h-3" /> 正方论据
            </div>
            <p className="text-sm text-gray-700">{debate.proponent_argument}</p>
          </div>

          {/* 反方 */}
          <div className="p-3 bg-red-50 border-l-4 border-red-400 rounded">
            <div className="flex items-center gap-1 text-xs font-medium text-red-700 mb-1">
              <XCircle className="w-3 h-3" /> 反方论据
            </div>
            <p className="text-sm text-gray-700">{debate.opponent_argument}</p>
          </div>

          {/* 裁判 */}
          {debate.judge_assessment && (
            <div className="p-3 bg-gray-50 border-l-4 border-gray-400 rounded">
              <div className="flex items-center gap-1 text-xs font-medium text-gray-700 mb-1">
                <Gavel className="w-3 h-3" /> 裁判评估
              </div>
              <p className="text-sm text-gray-600">{debate.judge_assessment}</p>
            </div>
          )}

          {/* 修正后假设 */}
          {debate.refined_hypothesis && (
            <div className="p-3 bg-green-50 border border-green-200 rounded">
              <div className="text-xs font-medium text-green-700 mb-1">辩论后修正假设</div>
              <p className="text-sm text-gray-700">{debate.refined_hypothesis}</p>
            </div>
          )}

          {debate.mechanism_agreed != null && (
            <div className="text-xs text-gray-400">
              核心机制{debate.mechanism_agreed ? '已达成一致' : '未达成一致'}
            </div>
          )}
        </div>
      ))}
    </div>
  );
}
