'use client';

import { useQuery } from '@tanstack/react-query';
import { getRankings } from '@/lib/api';
import type { RankedHypothesis } from '@/types/coscientist';
import { Loader2, Trophy, Brain, FlaskRound, ShieldCheck, AlertTriangle, Lightbulb } from 'lucide-react';

const STRATEGY_LABELS: Record<string, string> = {
  initial: '初始',
  enhancement: '增强',
  combination: '合并',
  simplification: '简化',
};

function ScoreBar({ label, value, icon: Icon, color }: { label: string; value?: number | null; icon: typeof Brain; color: string }) {
  if (value == null) return null;
  const pct = Math.min(100, (value / 10) * 100);
  return (
    <div className="flex items-center gap-1.5 text-xs">
      <Icon className={`w-3 h-3 ${color}`} />
      <span className="text-gray-500 w-16">{label}</span>
      <div className="flex-1 h-1.5 bg-gray-200 rounded-full overflow-hidden">
        <div className={`h-full ${color.replace('text-', 'bg-')}`} style={{ width: `${pct}%` }} />
      </div>
      <span className="text-gray-600 font-medium w-8 text-right">{value.toFixed(1)}</span>
    </div>
  );
}

export default function HypothesisRanking({ runId }: { runId: string }) {
  const { data, isLoading } = useQuery({
    queryKey: ['coscientist-rankings', runId],
    queryFn: () => getRankings(runId),
    enabled: !!runId,
    refetchInterval: 5000,
  });

  if (isLoading) {
    return (
      <div className="flex items-center justify-center py-8">
        <Loader2 className="w-5 h-5 animate-spin text-gray-400" />
      </div>
    );
  }

  const rankings: RankedHypothesis[] = data?.rankings ?? [];

  if (rankings.length === 0) {
    return (
      <div className="text-center py-8 text-gray-400 text-sm">
        排名尚未生成 — 等待 Generation + Ranking 阶段完成
      </div>
    );
  }

  return (
    <div className="space-y-3">
      <div className="flex items-center gap-2 mb-2">
        <Trophy className="w-4 h-4 text-amber-500" />
        <h3 className="text-sm font-semibold text-gray-700">
          假设排名（共 {data?.total_hypotheses ?? rankings.length} 个）
        </h3>
        {data?.round_num && (
          <span className="text-xs text-gray-400">第 {data.round_num} 轮</span>
        )}
      </div>

      {rankings.map((hyp, idx) => {
        const rank = hyp.rank ?? idx + 1;
        const medal = rank === 1 ? '🥇' : rank === 2 ? '🥈' : rank === 3 ? '🥉' : `#${rank}`;
        return (
          <div key={hyp.id} className="p-4 bg-white border border-gray-200 rounded-lg">
            <div className="flex items-start justify-between mb-2">
              <div className="flex items-center gap-2">
                <span className="text-lg font-bold">{medal}</span>
                <div>
                  <h4 className="text-sm font-semibold text-gray-800">{hyp.name}</h4>
                  {hyp.evolution_strategy && (
                    <span className="text-xs text-indigo-500">
                      {STRATEGY_LABELS[hyp.evolution_strategy] ?? hyp.evolution_strategy}
                    </span>
                  )}
                </div>
              </div>
              <div className="text-right">
                <div className="text-lg font-bold text-indigo-600">{hyp.elo_score.toFixed(0)}</div>
                <div className="text-xs text-gray-400">Elo</div>
                {hyp.experimental_validation_count != null && hyp.experimental_validation_count > 0 && (
                  <div className="text-xs text-green-600 font-medium whitespace-nowrap">
                    🧪 实验验证 ×{hyp.experimental_validation_count}
                    {hyp.experimental_elo_adjustment != null && (
                      <span> · {hyp.experimental_elo_adjustment > 0 ? '+' : ''}{hyp.experimental_elo_adjustment.toFixed(1)} Elo</span>
                    )}
                  </div>
                )}
              </div>
            </div>

            {hyp.description && (
              <p className="text-xs text-gray-600 mb-2">{hyp.description}</p>
            )}
            {hyp.mechanism && (
              <p className="text-xs text-gray-500 mb-2 italic">{hyp.mechanism}</p>
            )}

            {/* 评分维度 */}
            <div className="space-y-1 mt-2">
              <ScoreBar label="新颖性" value={hyp.novelty_score} icon={Lightbulb} color="text-yellow-500" />
              <ScoreBar label="可信度" value={hyp.plausibility_score} icon={Brain} color="text-blue-500" />
              <ScoreBar label="可测试" value={hyp.testability_score} icon={FlaskRound} color="text-green-500" />
              <ScoreBar label="安全性" value={hyp.safety_score} icon={ShieldCheck} color="text-purple-500" />
            </div>

            {hyp.critique_summary && (
              <div className="mt-2 p-2 bg-amber-50 rounded text-xs text-amber-800 flex items-start gap-1">
                <AlertTriangle className="w-3 h-3 mt-0.5 flex-shrink-0" />
                <span>{hyp.critique_summary}</span>
              </div>
            )}

            {hyp.parent_ids && hyp.parent_ids.length > 0 && (
              <div className="mt-2 text-xs text-gray-400">
                父假设: {hyp.parent_ids.join(', ')}
              </div>
            )}
          </div>
        );
      })}
    </div>
  );
}
