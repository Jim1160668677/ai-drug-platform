'use client';

/**
 * DecisionChainList — 决策链列表（组件 10/18）
 *
 * 展示 decisions 数组，用颜色区分 keep/discard，每条可展开 raw 数据。
 * 端点：GET /intelligence/runs/{id}/decisions
 */
import { useState } from 'react';
import { useQuery } from '@tanstack/react-query';
import { CheckCircle, XCircle, ChevronDown, ChevronRight, GitBranch } from 'lucide-react';
import clsx from 'clsx';
import Card from '@/components/ui/Card';
import EmptyState from '@/components/ui/EmptyState';
import { SkeletonList } from '@/components/ui/Skeleton';
import { getDecisionChain } from '@/lib/api';

interface DecisionChainListProps {
  runId: string;
}

export default function DecisionChainList({ runId }: DecisionChainListProps) {
  const [expanded, setExpanded] = useState<Set<number>>(new Set());
  const { data, isLoading } = useQuery({
    queryKey: ['intelligence-decisions', runId],
    queryFn: () => getDecisionChain(runId),
    enabled: !!runId,
  });

  if (isLoading) {
    return <Card title="决策链"><SkeletonList count={3} /></Card>;
  }

  if (!data || data.decisions.length === 0) {
    return <Card title="决策链"><EmptyState icon={GitBranch} title="暂无决策记录" /></Card>;
  }

  const toggle = (idx: number) => {
    setExpanded((prev) => {
      const next = new Set(prev);
      if (next.has(idx)) next.delete(idx);
      else next.add(idx);
      return next;
    });
  };

  return (
    <Card title={`决策链 (${data.decisions.length})`}>
      <ul className="space-y-2">
        {data.decisions.map((decision, idx) => {
          const basis = (decision.decision_basis || decision.basis || '') as string;
          const action = (decision.action || decision.keep !== undefined ? (decision.keep ? 'keep' : 'discard') : '') as string;
          const isKeep = action === 'keep' || action === 'accept';
          const isDiscard = action === 'discard' || action === 'reject';
          const isExpanded = expanded.has(idx);

          return (
            <li key={idx} className="border border-gray-100 rounded-md overflow-hidden">
              <div
                className="flex items-start gap-2 p-2.5 cursor-pointer hover:bg-gray-50"
                onClick={() => toggle(idx)}
              >
                {isKeep ? <CheckCircle className="w-4 h-4 text-green-500 flex-shrink-0 mt-0.5" />
                : isDiscard ? <XCircle className="w-4 h-4 text-red-500 flex-shrink-0 mt-0.5" />
                : <GitBranch className="w-4 h-4 text-gray-400 flex-shrink-0 mt-0.5" />}

                <div className="flex-1 min-w-0">
                  <p className="text-sm text-gray-700 break-words line-clamp-2">{basis || JSON.stringify(decision).slice(0, 100)}</p>
                  {action && (
                    <span className={clsx('inline-block mt-0.5 px-1.5 py-0.5 rounded text-xs font-medium',
                      isKeep ? 'bg-green-100 text-green-700' : isDiscard ? 'bg-red-100 text-red-700' : 'bg-gray-100 text-gray-600'
                    )}>{action}</span>
                  )}
                </div>

                {isExpanded ? <ChevronDown className="w-4 h-4 text-gray-400 flex-shrink-0" /> : <ChevronRight className="w-4 h-4 text-gray-400 flex-shrink-0" />}
              </div>

              {isExpanded && (
                <pre className="px-3 py-2 bg-gray-50 text-xs text-gray-600 overflow-x-auto border-t border-gray-100">
                  {JSON.stringify(decision, null, 2)}
                </pre>
              )}
            </li>
          );
        })}
      </ul>
    </Card>
  );
}
