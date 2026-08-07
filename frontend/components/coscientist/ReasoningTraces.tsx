'use client';

import { useState, useMemo } from 'react';
import { ChevronDown, ChevronRight, Cpu, Zap, GitBranch, Clock, DollarSign, CheckCircle2, AlertCircle, Loader2 } from 'lucide-react';
import type { ReasoningTrace } from '@/hooks/useUnifiedAgent';

interface ReasoningTracesProps {
  traces: ReasoningTrace[];
  isLoading?: boolean;
}

const STEP_TYPE_META: Record<string, { label: string; icon: string; color: string }> = {
  agent_call: { label: 'Agent 调用', icon: '🤖', color: 'blue' },
  llm_call: { label: 'LLM 调用', icon: '🧠', color: 'purple' },
  tool_call: { label: '工具调用', icon: '🔧', color: 'green' },
  decision_point: { label: '决策点', icon: '⚖️', color: 'amber' },
  phase_start: { label: '阶段开始', icon: '▶️', color: 'gray' },
  phase_end: { label: '阶段结束', icon: '⏹️', color: 'gray' },
  round_start: { label: '轮次开始', icon: '🔄', color: 'blue' },
  round_end: { label: '轮次结束', icon: '✅', color: 'blue' },
  debate: { label: '辩论', icon: '💬', color: 'orange' },
  ranking: { label: '排名', icon: '🏆', color: 'yellow' },
  evolution: { label: '进化', icon: '🌱', color: 'green' },
  feedback: { label: '反馈', icon: '📝', color: 'gray' },
  user_message: { label: '用户消息', icon: '👤', color: 'blue' },
  assistant_message: { label: '助手消息', icon: '🤖', color: 'purple' },
};

const AGENT_COLORS: Record<string, string> = {
  generation: 'bg-blue-100 text-blue-700 border-blue-200',
  proximity: 'bg-cyan-100 text-cyan-700 border-cyan-200',
  reflection: 'bg-purple-100 text-purple-700 border-purple-200',
  debate: 'bg-orange-100 text-orange-700 border-orange-200',
  ranking: 'bg-yellow-100 text-yellow-700 border-yellow-200',
  evolution: 'bg-green-100 text-green-700 border-green-200',
  meta_review: 'bg-indigo-100 text-indigo-700 border-indigo-200',
};

function getStepMeta(type: string) {
  return STEP_TYPE_META[type] || { label: type, icon: '📌', color: 'gray' };
}

function StatusBadge({ status }: { status: string }) {
  const config = {
    completed: { icon: CheckCircle2, cls: 'text-green-600 bg-green-50' },
    started: { icon: Loader2, cls: 'text-blue-600 bg-blue-50' },
    failed: { icon: AlertCircle, cls: 'text-red-600 bg-red-50' },
  }[status] || { icon: CheckCircle2, cls: 'text-gray-600 bg-gray-50' };
  const Icon = config.icon;
  return (
    <span className={`inline-flex items-center gap-0.5 px-1.5 py-0.5 rounded text-[9px] ${config.cls}`}>
      <Icon className="w-2.5 h-2.5" />
      {status}
    </span>
  );
}

function StepNode({ step, depth = 0 }: { step: ReasoningTrace; depth?: number }) {
  const [expanded, setExpanded] = useState(depth < 1);
  const meta = getStepMeta(step.step_type);
  const hasChildren = step.children && step.children.length > 0;

  const agentBadge = step.agent_name ? AGENT_COLORS[step.agent_name] || 'bg-gray-100 text-gray-700 border-gray-200' : null;

  return (
    <div className={`relative pl-${depth * 4} py-1`}>
      {depth > 0 && (
        <div className={`absolute left-0 top-0 bottom-0 border-l-2 border-dashed border-gray-200 ml-2`} />
      )}
      <div className={`rounded-lg border px-2 py-1.5 bg-white hover:bg-gray-50 transition-colors`}>
        <div className="flex items-center gap-1.5 flex-wrap">
          {hasChildren ? (
            <button
              onClick={() => setExpanded(!expanded)}
              className="p-0.5 rounded hover:bg-gray-200"
            >
              {expanded ? <ChevronDown className="w-3 h-3" /> : <ChevronRight className="w-3 h-3" />}
            </button>
          ) : (
            <span className="w-4" />
          )}
          <span className="text-sm">{meta.icon}</span>
          <span className="text-[11px] font-medium text-gray-700">{meta.label}</span>
          {step.agent_name && (
            <span className={`inline-flex items-center px-1 py-0.5 rounded text-[9px] border ${agentBadge}`}>
              {step.agent_name}
            </span>
          )}
          {step.phase && (
            <span className="inline-flex items-center px-1 py-0.5 rounded text-[9px] bg-gray-100 text-gray-500">
              {step.phase}
            </span>
          )}
          {step.round_num != null && (
            <span className="inline-flex items-center px-1 py-0.5 rounded text-[9px] bg-indigo-50 text-indigo-600">
              轮次 {step.round_num}
            </span>
          )}
          <StatusBadge status={step.status} />
          {step.duration_sec != null && step.duration_sec > 0 && (
            <span className="inline-flex items-center gap-0.5 text-[9px] text-gray-400">
              <Clock className="w-2.5 h-2.5" />
              {step.duration_sec.toFixed(1)}s
            </span>
          )}
          {step.cost_usd != null && step.cost_usd > 0 && (
            <span className="inline-flex items-center gap-0.5 text-[9px] text-amber-600">
              <DollarSign className="w-2.5 h-2.5" />
              ${step.cost_usd.toFixed(4)}
            </span>
          )}
          {step.created_at && (
            <span className="text-[9px] text-gray-300 ml-auto">
              {new Date(step.created_at).toLocaleTimeString()}
            </span>
          )}
        </div>

        {expanded && (
          <div className="mt-1 space-y-1">
            {step.input_data && Object.keys(step.input_data).length > 0 && (
              <details className="group">
                <summary className="cursor-pointer text-[9px] text-gray-400 hover:text-gray-600 flex items-center gap-0.5">
                  <ChevronRight className="w-2 h-2 group-open:rotate-90 transition-transform" />
                  输入数据
                </summary>
                <pre className="mt-0.5 text-[9px] bg-gray-50 rounded p-1.5 overflow-x-auto max-h-24">
                  {JSON.stringify(step.input_data, null, 2).slice(0, 500)}
                </pre>
              </details>
            )}
            {step.output_data && Object.keys(step.output_data).length > 0 && (
              <details className="group">
                <summary className="cursor-pointer text-[9px] text-gray-400 hover:text-gray-600 flex items-center gap-0.5">
                  <ChevronRight className="w-2 h-2 group-open:rotate-90 transition-transform" />
                  输出结果
                </summary>
                <pre className="mt-0.5 text-[9px] bg-indigo-50 rounded p-1.5 overflow-x-auto max-h-32">
                  {JSON.stringify(step.output_data, null, 2).slice(0, 800)}
                </pre>
              </details>
            )}
            {step.decision_basis && (
              <div className="rounded border border-amber-200 bg-amber-50 p-1.5">
                <div className="text-[9px] font-medium text-amber-700 flex items-center gap-0.5">
                  <GitBranch className="w-2.5 h-2.5" />
                  决策依据
                </div>
                <div className="text-[10px] text-amber-800 mt-0.5">{step.decision_basis}</div>
              </div>
            )}
            {step.error && (
              <div className="rounded border border-red-200 bg-red-50 p-1">
                <div className="text-[9px] text-red-700">⚠️ {step.error}</div>
              </div>
            )}
          </div>
        )}

        {hasChildren && expanded && (
          <div className="mt-1 space-y-0.5">
            {step.children!.map((child) => (
              <StepNode key={child.id} step={child} depth={depth + 1} />
            ))}
          </div>
        )}
      </div>
    </div>
  );
}

function TimelineView({ traces }: { traces: ReasoningTrace[] }) {
  const flatSteps = useMemo(() => {
    const result: ReasoningTrace[] = [];
    const flatten = (steps: ReasoningTrace[]) => {
      for (const step of steps) {
        result.push(step);
        if (step.children?.length) {
          flatten(step.children);
        }
      }
    };
    flatten(traces);
    return result.sort((a, b) => {
      const ta = a.created_at ? new Date(a.created_at).getTime() : 0;
      const tb = b.created_at ? new Date(b.created_at).getTime() : 0;
      return ta - tb;
    });
  }, [traces]);

  if (flatSteps.length === 0) {
    return (
      <div className="text-center py-4 text-xs text-gray-400">
        暂无推理轨迹数据
      </div>
    );
  }

  return (
    <div className="relative">
      <div className="absolute left-[15px] top-0 bottom-0 w-px bg-gradient-to-b from-indigo-200 via-gray-200 to-transparent" />
      {flatSteps.map((step) => {
        const meta = getStepMeta(step.step_type);
        return (
          <div key={step.id} className="relative pl-9 py-1.5">
            <div className="absolute left-2.5 w-5 h-5 rounded-full bg-white border-2 border-indigo-300 flex items-center justify-center text-[10px] z-10">
              {meta.icon}
            </div>
            <div className="rounded border border-gray-100 bg-white px-2 py-1 hover:shadow-sm transition-shadow">
              <div className="flex items-center gap-1 flex-wrap">
                <span className="text-[10px] font-medium text-gray-700">{meta.label}</span>
                {step.agent_name && (
                  <span className="text-[9px] text-gray-400">· {step.agent_name}</span>
                )}
                {step.duration_sec != null && step.duration_sec > 0 && (
                  <span className="text-[9px] text-gray-400">{step.duration_sec.toFixed(1)}s</span>
                )}
                {step.cost_usd != null && step.cost_usd > 0 && (
                  <span className="text-[9px] text-amber-500">${step.cost_usd.toFixed(4)}</span>
                )}
              </div>
              {step.decision_basis && (
                <div className="mt-0.5 text-[9px] text-amber-700 bg-amber-50 rounded px-1 py-0.5">
                  ⚖️ {step.decision_basis.slice(0, 100)}
                </div>
              )}
            </div>
          </div>
        );
      })}
    </div>
  );
}

function FlowView({ traces }: { traces: ReasoningTrace[] }) {
  return (
    <div className="space-y-0.5">
      {traces.map((root) => (
        <StepNode key={root.id} step={root} depth={0} />
      ))}
    </div>
  );
}

export default function ReasoningTraces({ traces, isLoading }: ReasoningTracesProps) {
  const [viewMode, setViewMode] = useState<'timeline' | 'flow'>('timeline');

  if (isLoading) {
    return (
      <div className="flex items-center justify-center py-4 text-xs text-gray-500 gap-1.5">
        <Loader2 className="w-3 h-3 animate-spin" />
        正在加载推理轨迹...
      </div>
    );
  }

  if (!traces || traces.length === 0) {
    return null;
  }

  const totalSteps = useMemo(() => {
    let count = 0;
    const countSteps = (steps: ReasoningTrace[]) => {
      for (const step of steps) {
        count++;
        if (step.children?.length) countSteps(step.children);
      }
    };
    countSteps(traces);
    return count;
  }, [traces]);

  return (
    <div className="mt-3 border-t border-indigo-100 pt-3">
      <div className="flex items-center justify-between mb-2">
        <div className="flex items-center gap-1.5 text-xs font-medium text-indigo-700">
          <Cpu className="w-3 h-3" />
          <span>推理过程可视化</span>
          <span className="text-gray-400 text-[10px]">({totalSteps} 步骤)</span>
        </div>
        <div className="flex items-center gap-1">
          <button
            onClick={() => setViewMode('timeline')}
            className={`px-2 py-0.5 text-[10px] rounded transition-colors ${
              viewMode === 'timeline'
                ? 'bg-indigo-100 text-indigo-700'
                : 'bg-gray-100 text-gray-500 hover:bg-gray-200'
            }`}
          >
            <Clock className="w-2.5 h-2.5 inline mr-0.5" />
            时间轴
          </button>
          <button
            onClick={() => setViewMode('flow')}
            className={`px-2 py-0.5 text-[10px] rounded transition-colors ${
              viewMode === 'flow'
                ? 'bg-indigo-100 text-indigo-700'
                : 'bg-gray-100 text-gray-500 hover:bg-gray-200'
            }`}
          >
            <GitBranch className="w-2.5 h-2.5 inline mr-0.5" />
            流程图
          </button>
        </div>
      </div>

      <div className="max-h-60 overflow-y-auto pr-1">
        {viewMode === 'timeline' ? (
          <TimelineView traces={traces} />
        ) : (
          <FlowView traces={traces} />
        )}
      </div>
    </div>
  );
}