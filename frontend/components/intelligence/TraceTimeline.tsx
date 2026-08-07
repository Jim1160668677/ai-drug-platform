'use client';

/**
 * TraceTimeline — 推理追溯时间线（组件 7/18）
 *
 * 垂直时间轴展示推理步骤，点击 reasoning 步骤可选中 run_id 触发下游组件。
 * tool_call 步骤支持展开证据卡片，展示检索到的文献。
 * 端点：GET /intelligence/sessions/{id}/trace
 */
import { useState } from 'react';
import { useQuery } from '@tanstack/react-query';
import {
  MessageSquare, Brain, Bot, GitBranch, Wrench, DollarSign, Clock,
  CheckCircle, XCircle, Loader2, ChevronDown, ChevronRight, ExternalLink,
} from 'lucide-react';
import clsx from 'clsx';
import Card from '@/components/ui/Card';
import EmptyState from '@/components/ui/EmptyState';
import { SkeletonList } from '@/components/ui/Skeleton';
import { getTrace } from '@/lib/api';
import type { TraceStep } from '@/types/intelligence';

const SOURCE_COLORS: Record<string, string> = {
  pubmed: 'bg-blue-100 text-blue-700',
  biorxiv: 'bg-green-100 text-green-700',
  arxiv: 'bg-orange-100 text-orange-700',
  semantic_scholar: 'bg-purple-100 text-purple-700',
  crossref: 'bg-red-100 text-red-700',
};

interface TraceTimelineProps {
  sessionId: string;
  limit?: number;
  onSelectRun?: (runId: string) => void;
}

const STEP_ICONS: Record<string, typeof MessageSquare> = {
  user_message: MessageSquare,
  assistant_message: Brain,
  agent_call: Bot,
  llm_call: Brain,
  decision_point: GitBranch,
  tool_call: Wrench,
};

const STATUS_ICONS: Record<string, typeof CheckCircle> = {
  completed: CheckCircle,
  failed: XCircle,
  running: Loader2,
  pending: Clock,
};

export default function TraceTimeline({ sessionId, limit = 200, onSelectRun }: TraceTimelineProps) {
  const [expandedSteps, setExpandedSteps] = useState<Set<string>>(new Set());

  const { data, isLoading } = useQuery({
    queryKey: ['intelligence-trace', sessionId],
    queryFn: () => getTrace(sessionId, limit),
    enabled: !!sessionId,
  });

  const toggleStep = (stepId: string) => {
    setExpandedSteps(prev => {
      const next = new Set(prev);
      if (next.has(stepId)) {
        next.delete(stepId);
      } else {
        next.add(stepId);
      }
      return next;
    });
  };

  if (isLoading) {
    return (
      <Card title="推理追溯">
        <SkeletonList count={4} />
      </Card>
    );
  }

  if (!data || data.traces.length === 0) {
    return (
      <Card title="推理追溯">
        <EmptyState icon={GitBranch} title="暂无追溯记录" />
      </Card>
    );
  }

  return (
    <Card
      title={`推理追溯 (${data.total_steps})`}
      action={<span className="text-xs text-gray-400">{data.traces.length} 步</span>}
    >
      <div className="relative">
        {/* 时间轴竖线 */}
        <div className="absolute left-4 top-0 bottom-0 w-0.5 bg-gray-200" />

        <ul className="space-y-3">
          {data.traces.map((step: TraceStep, idx: number) => {
            const StepIcon = STEP_ICONS[step.step_type] ?? MessageSquare;
            const StatusIcon = STATUS_ICONS[step.status] ?? CheckCircle;
            const isLast = idx === data.traces.length - 1;
            const hasEvidence = step.step_type === 'tool_call' && step.evidence && step.evidence.papers.length > 0;
            const isExpanded = expandedSteps.has(step.id);

            return (
              <li key={step.id} className="relative pl-10">
                {/* 节点圆 */}
                <div
                  className={clsx(
                    'absolute left-2.5 top-1 w-4 h-4 rounded-full flex items-center justify-center ring-4 ring-white',
                    step.status === 'completed' ? 'bg-green-500'
                    : step.status === 'failed' ? 'bg-red-500'
                    : step.status === 'running' ? 'bg-blue-500'
                    : 'bg-gray-400',
                  )}
                >
                  <StepIcon className="w-2.5 h-2.5 text-white" />
                </div>

                <div
                  className="p-2 rounded-md hover:bg-gray-50 cursor-pointer transition-colors"
                  onClick={() => {
                    if (hasEvidence) {
                      toggleStep(step.id);
                      return;
                    }
                    const runId = (step as any).run_id;
                    if (runId && onSelectRun) onSelectRun(runId);
                  }}
                >
                  <div className="flex items-center gap-2 flex-wrap">
                    {hasEvidence && (
                      isExpanded
                        ? <ChevronDown className="w-3.5 h-3.5 text-gray-500" />
                        : <ChevronRight className="w-3.5 h-3.5 text-gray-500" />
                    )}
                    <span className="text-xs font-medium text-gray-700">
                      {step.step_type.replace(/_/g, ' ')}
                    </span>
                    {step.agent_name && (
                      <span className="text-xs text-purple-600">@{step.agent_name}</span>
                    )}
                    {step.phase && (
                      <span className="text-xs text-blue-600">[{step.phase}]</span>
                    )}
                    {step.round_num != null && (
                      <span className="text-xs text-gray-400">R{step.round_num}</span>
                    )}
                    <StatusIcon
                      className={clsx(
                        'w-3.5 h-3.5 ml-auto',
                        step.status === 'completed' ? 'text-green-500'
                        : step.status === 'failed' ? 'text-red-500'
                        : step.status === 'running' ? 'text-blue-500 animate-spin'
                        : 'text-gray-400',
                      )}
                    />
                  </div>

                  {step.decision_basis && (
                    <p className="text-xs text-gray-500 mt-1 line-clamp-2">
                      {step.decision_basis}
                    </p>
                  )}

                  {/* 成本与时间 */}
                  <div className="flex items-center gap-3 mt-1">
                    {step.cost_usd != null && step.cost_usd > 0 && (
                      <span className="flex items-center gap-0.5 text-xs text-gray-400">
                        <DollarSign className="w-3 h-3" />
                        {step.cost_usd.toFixed(4)}
                      </span>
                    )}
                    {step.duration_sec != null && step.duration_sec > 0 && (
                      <span className="flex items-center gap-0.5 text-xs text-gray-400">
                        <Clock className="w-3 h-3" />
                        {step.duration_sec.toFixed(2)}s
                      </span>
                    )}
                    {step.created_at && (
                      <span className="text-xs text-gray-400 ml-auto">
                        {new Date(step.created_at).toLocaleTimeString('zh-CN')}
                      </span>
                    )}
                  </div>
                </div>

                {/* 展开的证据卡片 */}
                {hasEvidence && isExpanded && step.evidence && (
                  <div className="mt-2 ml-1 p-3 bg-gray-50 border border-gray-200 rounded-md space-y-2">
                    {/* 查询摘要 */}
                    <div className="text-xs text-gray-600">
                      📎 证据: 检索 &quot;{step.evidence.query}&quot; (
                      {Object.entries(step.evidence.total_hits).map(([src, count], i) => (
                        <span key={src}>
                          {i > 0 ? ' + ' : ''}{src} {count}
                        </span>
                      ))}
                      )
                    </div>

                    {/* 文献卡片 */}
                    <div className="space-y-2 max-h-80 overflow-y-auto">
                      {step.evidence.papers.map(paper => (
                        <div key={paper.id} className="bg-white p-2 rounded border border-gray-100">
                          <a
                            href={paper.url || (paper.doi ? `https://doi.org/${paper.doi}` : '#')}
                            target="_blank"
                            rel="noopener noreferrer"
                            className="text-xs font-medium text-blue-600 hover:underline flex items-start gap-1"
                          >
                            <ExternalLink className="w-3 h-3 mt-0.5 shrink-0" />
                            <span>{paper.title}</span>
                          </a>
                          {paper.authors && paper.authors.length > 0 && (
                            <p className="text-xs text-gray-500 mt-1">
                              {paper.authors.slice(0, 3).join(', ')}{paper.authors.length > 3 ? ' et al.' : ''}
                              {paper.year && ` (${paper.year})`}
                            </p>
                          )}
                          <div className="flex items-center gap-2 mt-1">
                            {paper.doi && (
                              <span className="text-xs text-gray-400">{paper.doi}</span>
                            )}
                            <span className={clsx(
                              'text-xs px-1.5 py-0.5 rounded-full font-medium',
                              SOURCE_COLORS[paper.source] ?? 'bg-gray-100 text-gray-600',
                            )}>
                              {paper.source}
                            </span>
                          </div>
                        </div>
                      ))}
                    </div>
                  </div>
                )}

                {!isLast && <div className="border-l-0" />}
              </li>
            );
          })}
        </ul>
      </div>
    </Card>
  );
}
