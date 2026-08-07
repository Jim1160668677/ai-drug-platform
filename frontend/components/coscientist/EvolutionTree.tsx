'use client';

import { useQuery } from '@tanstack/react-query';
import { getEvolutionTree } from '@/lib/api';
import type { EvolutionNode, EvolutionEdge } from '@/types/coscientist';
import { Loader2, GitBranch, ArrowRight } from 'lucide-react';

const STRATEGY_COLORS: Record<string, string> = {
  initial: 'bg-gray-100 border-gray-300 text-gray-700',
  enhancement: 'bg-blue-50 border-blue-300 text-blue-700',
  combination: 'bg-purple-50 border-purple-300 text-purple-700',
  simplification: 'bg-green-50 border-green-300 text-green-700',
};

export default function EvolutionTree({ runId }: { runId: string }) {
  const { data, isLoading } = useQuery({
    queryKey: ['coscientist-evolution-tree', runId],
    queryFn: () => getEvolutionTree(runId),
    enabled: !!runId,
  });

  if (isLoading) {
    return (
      <div className="flex items-center justify-center py-8">
        <Loader2 className="w-5 h-5 animate-spin text-gray-400" />
      </div>
    );
  }

  const nodes: EvolutionNode[] = data?.nodes ?? [];
  const edges: EvolutionEdge[] = data?.edges ?? [];

  if (nodes.length === 0) {
    return (
      <div className="text-center py-8 text-gray-400 text-sm">
        暂无进化树 — 假设进化在 Evolution 阶段产生
      </div>
    );
  }

  // 按轮次分组
  const rounds = new Map<number, EvolutionNode[]>();
  for (const node of nodes) {
    const arr = rounds.get(node.round_num) ?? [];
    arr.push(node);
    rounds.set(node.round_num, arr);
  }
  const sortedRounds = Array.from(rounds.keys()).sort((a, b) => a - b);

  // 查找节点的父节点
  const nodeMap = new Map(nodes.map((n) => [n.hypothesis_id, n]));

  return (
    <div className="space-y-4">
      <div className="flex items-center gap-2 mb-2">
        <GitBranch className="w-4 h-4 text-indigo-500" />
        <h3 className="text-sm font-semibold text-gray-700">
          假设进化树（{nodes.length} 节点，{edges.length} 边，{data?.total_rounds ?? 0} 轮）
        </h3>
      </div>

      <div className="space-y-4">
        {sortedRounds.map((roundNum) => {
          const roundNodes = rounds.get(roundNum)!;
          return (
            <div key={roundNum}>
              <div className="text-xs font-medium text-gray-400 mb-2">第 {roundNum} 轮</div>
              <div className="grid grid-cols-1 md:grid-cols-2 gap-2">
                {roundNodes.map((node) => {
                  const colorClass = STRATEGY_COLORS[node.evolution_strategy] ?? STRATEGY_COLORS.initial;
                  const parents = node.parent_ids
                    ?.map((pid) => nodeMap.get(pid))
                    .filter(Boolean) as EvolutionNode[] | undefined;

                  return (
                    <div key={node.hypothesis_id} className={`p-3 border rounded-lg ${colorClass}`}>
                      {parents && parents.length > 0 && (
                        <div className="flex items-center gap-1 text-xs text-gray-500 mb-1">
                          {parents.map((p, i) => (
                            <span key={p.hypothesis_id}>
                              {i > 0 && <span className="mx-1">+</span>}
                              <span className="truncate max-w-[80px] inline-block align-bottom">{p.name}</span>
                            </span>
                          ))}
                          <ArrowRight className="w-3 h-3 mx-1" />
                        </div>
                      )}
                      <div className="flex items-center justify-between">
                        <span className="text-sm font-medium">{node.name}</span>
                        <span className="text-xs font-bold">{node.elo_score.toFixed(0)}</span>
                      </div>
                      <div className="text-xs opacity-70 mt-0.5">
                        {node.evolution_strategy}
                        {node.rank && ` · 排名 #${node.rank}`}
                      </div>
                    </div>
                  );
                })}
              </div>
            </div>
          );
        })}
      </div>
    </div>
  );
}
