/**
 * ReAct 步骤时间线：step → (thought) → action + action_input → observation
 * 每行显示 duration/tokens/cost。设计上与 COSMIC/OpenAI Traces 视觉一致。
 */
'use client';

import { Bot, Cpu, AlertTriangle, Check } from 'lucide-react';
import clsx from 'clsx';

export type StepStatus = 'running' | 'done' | 'error' | 'skipped';

export interface StepTraceEvent {
  step: number;
  thought?: string;
  action?: string;
  action_input?: Record<string, unknown> | null;
  observation?: string;
  duration_ms?: number;
  tokens?: number;
  cost_usd?: number;
  status?: StepStatus;
}

export interface StepTraceTimelineProps {
  events: StepTraceEvent[];
}

export default function StepTraceTimeline({ events }: StepTraceTimelineProps) {
  const sorted = [...events].sort((a, b) => a.step - b.step);
  return (
    <div className="space-y-2 text-xs">
      <div className="flex items-center gap-1.5 text-gray-500">
        <span className="font-medium text-gray-700">ReAct 步骤时间线</span>
        <span>· {sorted.length} 步</span>
      </div>
      {sorted.length === 0 && (
        <div className="text-gray-400 text-center py-6 border border-dashed border-gray-200 rounded-md">
          暂无步骤记录（Agent 运行后将展示每步 thought/action/observation）
        </div>
      )}
      <ol className="relative border-l border-gray-200 ml-2 space-y-2 pl-4">
        {sorted.map((ev) => {
          const st = ev.status ?? 'running';
          return (
            <li key={ev.step} className="space-y-1">
              <div className="flex items-center justify-between gap-2">
                <div className="flex items-center gap-1.5 text-gray-500">
                  {st === 'done'  && <Check        className="w-3 h-3 text-green-600" />}
                  {st === 'error' && <AlertTriangle className="w-3 h-3 text-red-600" />}
                  {st === 'running' && <Cpu          className="w-3 h-3 text-blue-600 animate-pulse" />}
                  {st === 'skipped' && <Bot         className="w-3 h-3 text-gray-400" />}
                  <span className="font-semibold text-gray-700">Step {ev.step}</span>
                  {ev.action && (
                    <span className="px-1.5 py-0.5 bg-indigo-50 text-indigo-700 rounded border border-indigo-100 font-mono">
                      {ev.action}
                    </span>
                  )}
                </div>
                <div className="text-[10px] text-gray-500 font-mono">
                  {ev.duration_ms ?? 0}ms · {ev.tokens ?? 0}tok · ${(ev.cost_usd ?? 0).toFixed(4)}
                </div>
              </div>
              {ev.thought && (
                <div className="text-gray-600 italic line-clamp-3">💭 {ev.thought}</div>
              )}
              {ev.action_input && (
                <pre className="rounded bg-gray-50 p-1.5 text-[11px] text-gray-700 overflow-x-auto whitespace-pre-wrap break-all max-h-24">
                  {JSON.stringify(ev.action_input, null, 0)}
                </pre>
              )}
              {ev.observation && (
                <div className={clsx(
                  'rounded border p-1.5 text-gray-600 max-h-24 overflow-y-auto',
                  st === 'error' ? 'border-red-100 bg-red-50' : 'border-gray-100 bg-gray-50',
                )}>
                  {ev.observation}
                </div>
              )}
            </li>
          );
        })}
      </ol>
    </div>
  );
}
