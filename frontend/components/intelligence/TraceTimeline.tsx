'use client';

/**
 * TraceTimeline — 推理追溯时间线（组件 7/18）
 *
 * 垂直时间轴展示推理步骤，点击 reasoning 步骤可选中 run_id 触发下游组件。
 * tool_call 步骤支持展开证据卡片，展示检索到的文献。
 * 支持用户干预：调整检索词、添加数据源，重执行检索并创建新追溯步骤。
 * 端点：GET /intelligence/sessions/{id}/trace
 *       POST /knowledge/academic-search/reexecute
 */
import { useState, useCallback } from 'react';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import {
  MessageSquare, Brain, Bot, GitBranch, Wrench, DollarSign, Clock,
  CheckCircle, XCircle, Loader2, ChevronDown, ChevronRight, ExternalLink,
  RefreshCw, Plus, X, Search, Database,
} from 'lucide-react';
import clsx from 'clsx';
import Card from '@/components/ui/Card';
import EmptyState from '@/components/ui/EmptyState';
import { SkeletonList } from '@/components/ui/Skeleton';
import { getTrace, reexecuteAcademicSearch } from '@/lib/api';
import type { TraceStep } from '@/types/intelligence';

const ALL_SOURCES = ['pubmed', 'biorxiv', 'arxiv', 'semantic_scholar', 'crossref'] as const;
type SourceKey = typeof ALL_SOURCES[number];

interface ModalState {
  type: 'edit_query' | 'add_sources';
  stepId: string;
}

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
  const [modalState, setModalState] = useState<ModalState | null>(null);
  const [editQuery, setEditQuery] = useState('');
  const [selectedSources, setSelectedSources] = useState<Set<SourceKey>>(new Set());
  const queryClient = useQueryClient();

  const { data, isLoading } = useQuery({
    queryKey: ['intelligence-trace', sessionId],
    queryFn: () => getTrace(sessionId, limit),
    enabled: !!sessionId,
  });

  const reexecuteMutation = useMutation({
    mutationFn: (payload: { original_step_id: string; query?: string; add_sources?: string[] }) =>
      reexecuteAcademicSearch({ session_id: sessionId, ...payload }),
    onSuccess: (result) => {
      const newStep: TraceStep = {
        id: result.step_id,
        step_type: 'tool_call',
        status: 'completed',
        created_at: new Date().toISOString(),
        evidence: {
          query: result.query,
          sources: result.sources_queried,
          total_hits: result.total_hits,
          papers: result.papers,
        },
      };
      queryClient.setQueryData(['intelligence-trace', sessionId], (old: any) => {
        if (!old) return old;
        return { ...old, traces: [...old.traces, newStep], total_steps: old.total_steps + 1 };
      });
      setExpandedSteps(prev => new Set(prev).add(result.step_id));
      setModalState(null);
      setEditQuery('');
      setSelectedSources(new Set());
    },
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

  const openEditQuery = useCallback((step: TraceStep) => {
    setEditQuery(step.evidence?.query ?? '');
    setModalState({ type: 'edit_query', stepId: step.id });
  }, []);

  const openAddSources = useCallback((step: TraceStep) => {
    const current = new Set(step.evidence?.sources ?? []);
    setSelectedSources(current);
    setModalState({ type: 'add_sources', stepId: step.id });
  }, []);

  const closeModal = useCallback(() => {
    setModalState(null);
    setEditQuery('');
    setSelectedSources(new Set());
  }, []);

  const handleReexecute = useCallback(() => {
    if (!modalState) return;
    if (modalState.type === 'edit_query') {
      reexecuteMutation.mutate({ original_step_id: modalState.stepId, query: editQuery });
    } else {
      const currentStep = data?.traces.find((s: TraceStep) => s.id === modalState.stepId);
      const parentSources = new Set(currentStep?.evidence?.sources ?? []);
      const delta = ALL_SOURCES.filter(s => selectedSources.has(s) && !parentSources.has(s));
      reexecuteMutation.mutate({ original_step_id: modalState.stepId, add_sources: delta });
    }
  }, [modalState, editQuery, selectedSources, reexecuteMutation, data?.traces]);

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

                    {/* 干预按钮 */}
                    <div className="flex items-center gap-2 pt-1 border-t border-gray-200">
                      <button
                        type="button"
                        onClick={(e) => { e.stopPropagation(); openEditQuery(step); }}
                        className="flex items-center gap-1 text-xs text-blue-600 hover:text-blue-800 transition-colors"
                        aria-label="调整检索词"
                      >
                        <RefreshCw className="w-3 h-3" />
                        调整检索词
                      </button>
                      <button
                        type="button"
                        onClick={(e) => { e.stopPropagation(); openAddSources(step); }}
                        className="flex items-center gap-1 text-xs text-blue-600 hover:text-blue-800 transition-colors"
                        aria-label="添加数据源"
                      >
                        <Plus className="w-3 h-3" />
                        添加数据源
                      </button>
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

                {/* 干预 Modal */}
                {modalState && (
                  <div
                    className="fixed inset-0 z-50 flex items-center justify-center bg-black/40"
                    onClick={(e) => { if (e.target === e.currentTarget) closeModal(); }}
                  >
                    <div className="bg-white rounded-lg shadow-xl w-full max-w-md mx-4 p-4 space-y-3">
                      <div className="flex items-center justify-between">
                        <h3 className="text-sm font-medium text-gray-900">
                          {modalState.type === 'edit_query' ? (
                            <span className="flex items-center gap-1.5"><Search className="w-4 h-4" /> 调整检索词</span>
                          ) : (
                            <span className="flex items-center gap-1.5"><Database className="w-4 h-4" /> 选择数据源</span>
                          )}
                        </h3>
                        <button
                          type="button"
                          onClick={closeModal}
                          className="text-gray-400 hover:text-gray-600"
                          aria-label="关闭"
                        >
                          <X className="w-4 h-4" />
                        </button>
                      </div>

                      {modalState.type === 'edit_query' ? (
                        <input
                          type="text"
                          value={editQuery}
                          onChange={(e) => setEditQuery(e.target.value)}
                          onKeyDown={(e) => { if (e.key === 'Enter' && editQuery.trim()) handleReexecute(); }}
                          placeholder="输入新的检索词..."
                          className="w-full border border-gray-300 rounded-md px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
                          data-testid="edit-query-input"
                        />
                      ) : (
                        <div className="space-y-2" data-testid="source-checkboxes">
                          {ALL_SOURCES.map(src => (
                            <label key={src} className="flex items-center gap-2 text-sm text-gray-700 cursor-pointer">
                              <input
                                type="checkbox"
                                checked={selectedSources.has(src)}
                                onChange={() => {
                                  setSelectedSources(prev => {
                                    const next = new Set(prev);
                                    if (next.has(src)) next.delete(src);
                                    else next.add(src);
                                    return next;
                                  });
                                }}
                                className="rounded border-gray-300 text-blue-600 focus:ring-blue-500"
                              />
                              <span className={clsx(
                                'text-xs px-1.5 py-0.5 rounded-full font-medium',
                                SOURCE_COLORS[src] ?? 'bg-gray-100 text-gray-600',
                              )}>
                                {src}
                              </span>
                            </label>
                          ))}
                        </div>
                      )}

                      <div className="flex justify-end gap-2 pt-2 border-t border-gray-200">
                        <button
                          type="button"
                          onClick={closeModal}
                          className="px-3 py-1.5 text-xs text-gray-600 hover:text-gray-800 rounded-md hover:bg-gray-100"
                        >
                          取消
                        </button>
                        <button
                          type="button"
                          onClick={handleReexecute}
                          disabled={reexecuteMutation.isPending || (modalState.type === 'edit_query' && !editQuery.trim())}
                          className="px-3 py-1.5 text-xs text-white bg-blue-600 hover:bg-blue-700 rounded-md disabled:opacity-50 disabled:cursor-not-allowed flex items-center gap-1"
                        >
                          {reexecuteMutation.isPending && <Loader2 className="w-3 h-3 animate-spin" />}
                          {reexecuteMutation.isPending ? '检索中...' : '重新检索'}
                        </button>
                      </div>

                      {reexecuteMutation.isError && (
                        <p className="text-xs text-red-600">
                          检索失败: {reexecuteMutation.error?.message ?? '未知错误'}
                        </p>
                      )}
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
