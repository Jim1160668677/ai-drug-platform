/**
 * 7 阶段 DAG 可视化：
 * generation → reflection → proximity → evolution → debate → ranking → meta_review
 * 每节点显示 status (pending/running/done/error) + 气泡(duration/tokens/cost)
 * 按 round 折叠展开（round=0 初始生成；round>=1 辩论环）
 */
'use client';

import React from 'react';
import { CheckCircle2, Circle, Loader2, AlertCircle, ChevronRight, Coins, Timer, Hash } from 'lucide-react';
import clsx from 'clsx';

export type PhaseStatus = 'pending' | 'running' | 'done' | 'error';

export interface DagNodeStatusEvent {
  phase: string;
  round: number;
  status: PhaseStatus;
  duration_ms: number;
  tokens: number;
  cost_usd: number;
  extra?: Record<string, unknown>;
}

export interface DagPhaseTimelineProps {
  events: DagNodeStatusEvent[];
  maxRoundsShown?: number;
}

const SEVEN_PHASES = [
  { key: 'generation',  label: '假设生成', abbr: 'G' },
  { key: 'reflection',  label: '批判反思', abbr: 'R' },
  { key: 'proximity',   label: '邻近评估', abbr: 'P' },
  { key: 'evolution',   label: '进化策略', abbr: 'E' },
  { key: 'debate',      label: '辩论对抗', abbr: 'D' },
  { key: 'ranking',     label: 'ELO排名',  abbr: 'Rk' },
  { key: 'meta_review', label: '元审阅',   abbr: 'Mr' },
] as const;

function statusIcon(s: PhaseStatus) {
  switch (s) {
    case 'done':    return <CheckCircle2 className="w-4 h-4 text-green-600" />;
    case 'running': return <Loader2   className="w-4 h-4 text-blue-600 animate-spin" />;
    case 'error':   return <AlertCircle className="w-4 h-4 text-red-600" />;
    default:        return <Circle      className="w-4 h-4 text-gray-300" />;
  }
}

export default function DagPhaseTimeline({ events, maxRoundsShown = 5 }: DagPhaseTimelineProps) {
  const byRound = new Map<number, Map<string, DagNodeStatusEvent>>();
  for (const ev of events) {
    const roundMap = byRound.get(ev.round) ?? new Map<string, DagNodeStatusEvent>();
    roundMap.set(ev.phase, ev);
    byRound.set(ev.round, roundMap);
  }
  const sortedRounds = [...byRound.keys()].sort((a, b) => a - b).slice(0, maxRoundsShown);

  return (
    <div className="space-y-3 text-xs">
      <div className="flex items-center gap-1.5 text-gray-500">
        <span className="font-medium text-gray-700">7 阶段流程 DAG</span>
        <span>· 共 {sortedRounds.length} 轮</span>
      </div>

      {sortedRounds.length === 0 && (
        <div className="text-gray-400 text-center py-6 border border-dashed border-gray-200 rounded-md">
          暂无 DAG 事件（发送 Co-Scientist 请求后查看）
        </div>
      )}

      {sortedRounds.map((roundNum) => {
        const roundMap = byRound.get(roundNum)!;
        return (
          <div key={roundNum} className="rounded-md border border-gray-200 p-2.5">
            <div className="text-gray-500 mb-2">
              Round <span className="font-semibold text-gray-700">#{roundNum}</span>
            </div>
            <div className="flex items-start gap-1 overflow-x-auto">
              {SEVEN_PHASES.map((phase, idx) => {
                const ev = roundMap.get(phase.key);
                const s = ev?.status ?? 'pending';
                return (
                  <React.Fragment key={phase.key}>
                    <div
                      className={clsx(
                        'flex-shrink-0 min-w-[88px] rounded-md border px-2 py-1.5 flex flex-col gap-1',
                        s === 'running' && 'border-blue-300 bg-blue-50',
                        s === 'done'    && 'border-green-200 bg-green-50',
                        s === 'error'   && 'border-red-200 bg-red-50',
                        s === 'pending' && 'border-gray-200 bg-gray-50 opacity-70',
                      )}
                    >
                      <div className="flex items-center justify-between gap-1">
                        <span className="truncate text-gray-700">{phase.label}</span>
                        {statusIcon(s)}
                      </div>
                      {ev && (
                        <div className="space-y-0.5 text-[10px] text-gray-600">
                          <div className="flex items-center gap-1"><Timer className="w-3 h-3" />{ev.duration_ms}ms</div>
                          <div className="flex items-center gap-1"><Hash  className="w-3 h-3" />{ev.tokens}tok</div>
                          <div className="flex items-center gap-1"><Coins className="w-3 h-3" />${ev.cost_usd.toFixed?.(4) ?? '0'}</div>
                        </div>
                      )}
                    </div>
                    {idx < SEVEN_PHASES.length - 1 && (
                      <div className="flex-shrink-0 pt-3 text-gray-300">
                        <ChevronRight className="w-4 h-4" />
                      </div>
                    )}
                  </React.Fragment>
                );
              })}
            </div>
          </div>
        );
      })}
    </div>
  );
}
