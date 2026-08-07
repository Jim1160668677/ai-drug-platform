'use client';

import { useQuery } from '@tanstack/react-query';
import { getAgentStats } from '@/lib/api';
import type { AgentActivity } from '@/types/coscientist';
import { Loader2, Bot, Activity, DollarSign, Clock } from 'lucide-react';

const AGENT_LABELS: Record<string, string> = {
  generation: '假设生成',
  reflection: '反思评审',
  ranking: '排名评估',
  proximity: '相似度分析',
  evolution: '假设进化',
  meta_review: '元评审',
  feedback: '反馈处理',
  debate: '科学辩论',
};

const STATUS_COLORS: Record<string, string> = {
  idle: 'bg-gray-100 text-gray-500',
  running: 'bg-blue-100 text-blue-700 animate-pulse',
  completed: 'bg-green-100 text-green-700',
  failed: 'bg-red-100 text-red-700',
};

export default function AgentActivityFeed({ runId }: { runId: string }) {
  const { data, isLoading } = useQuery({
    queryKey: ['coscientist-agent-stats', runId],
    queryFn: () => getAgentStats(runId),
    enabled: !!runId,
    refetchInterval: 3000,
  });

  if (isLoading) {
    return (
      <div className="flex items-center justify-center py-8">
        <Loader2 className="w-5 h-5 animate-spin text-gray-400" />
      </div>
    );
  }

  const agents: AgentActivity[] = data?.agents ?? [];
  const totalCost = agents.reduce((sum, a) => sum + (a.cost_usd ?? 0), 0);
  const totalTokens = agents.reduce((sum, a) => {
    const u = a.token_usage;
    return sum + (u?.total ?? (u?.prompt ?? 0) + (u?.completion ?? 0));
  }, 0);

  if (agents.length === 0) {
    return (
      <div className="text-center py-8 text-gray-400 text-sm">
        暂无 Agent 活动 — 启动运行后显示
      </div>
    );
  }

  return (
    <div className="space-y-3">
      <div className="flex items-center gap-2 mb-2">
        <Activity className="w-4 h-4 text-blue-500" />
        <h3 className="text-sm font-semibold text-gray-700">Agent 活动状态</h3>
        {data?.current_phase && (
          <span className="text-xs px-2 py-0.5 bg-indigo-100 text-indigo-700 rounded-full">
            当前阶段: {data.current_phase}
          </span>
        )}
        {data?.current_round != null && (
          <span className="text-xs text-gray-400">轮次 {data.current_round}</span>
        )}
      </div>

      {/* 汇总 */}
      <div className="grid grid-cols-2 gap-2">
        <div className="p-2 bg-amber-50 border border-amber-200 rounded-lg flex items-center gap-2">
          <DollarSign className="w-4 h-4 text-amber-500" />
          <div>
            <div className="text-xs text-gray-500">总成本</div>
            <div className="text-sm font-medium">${totalCost.toFixed(4)}</div>
          </div>
        </div>
        <div className="p-2 bg-blue-50 border border-blue-200 rounded-lg flex items-center gap-2">
          <Clock className="w-4 h-4 text-blue-500" />
          <div>
            <div className="text-xs text-gray-500">总 Token</div>
            <div className="text-sm font-medium">{totalTokens.toLocaleString()}</div>
          </div>
        </div>
      </div>

      {/* Agent 列表 */}
      <div className="space-y-1.5">
        {agents.map((agent) => {
          const label = AGENT_LABELS[agent.agent_name] ?? agent.agent_name;
          const statusClass = STATUS_COLORS[agent.status] ?? STATUS_COLORS.idle;
          return (
            <div key={agent.agent_name} className="flex items-center gap-2 p-2 bg-white border border-gray-200 rounded-lg">
              <Bot className="w-4 h-4 text-gray-400 flex-shrink-0" />
              <div className="flex-1 min-w-0">
                <div className="flex items-center gap-2">
                  <span className="text-sm font-medium text-gray-700">{label}</span>
                  <span className={`text-xs px-1.5 py-0.5 rounded-full ${statusClass}`}>
                    {agent.status}
                  </span>
                </div>
                {agent.current_task && (
                  <div className="text-xs text-gray-400 truncate">{agent.current_task}</div>
                )}
                {agent.error && (
                  <div className="text-xs text-red-500 truncate">{agent.error}</div>
                )}
              </div>
              {agent.cost_usd != null && agent.cost_usd > 0 && (
                <span className="text-xs text-gray-400">${agent.cost_usd.toFixed(4)}</span>
              )}
            </div>
          );
        })}
      </div>
    </div>
  );
}
