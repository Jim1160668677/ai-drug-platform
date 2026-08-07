'use client';

/**
 * CostBreakdownChart — 成本分解图表（组件 9/18）
 *
 * 三张 plotly 图：by_agent 柱状、by_phase 饼图、by_step_type 柱状。
 * 端点：GET /intelligence/runs/{id}/cost
 */
import { useQuery } from '@tanstack/react-query';
import dynamic from 'next/dynamic';
import { DollarSign, Coins } from 'lucide-react';
import Card from '@/components/ui/Card';
import EmptyState from '@/components/ui/EmptyState';
import { getCostBreakdown } from '@/lib/api';

const Plot = dynamic(() => import('react-plotly.js'), { ssr: false });

interface CostBreakdownChartProps {
  runId: string;
}

function dictToEntries(d: Record<string, number>): Array<[string, number]> {
  return Object.entries(d).sort((a, b) => b[1] - a[1]);
}

export default function CostBreakdownChart({ runId }: CostBreakdownChartProps) {
  const { data, isLoading } = useQuery({
    queryKey: ['intelligence-cost', runId],
    queryFn: () => getCostBreakdown(runId),
    enabled: !!runId,
  });

  if (isLoading) {
    return <Card title="成本分解"><div className="h-48 flex items-center justify-center text-gray-400 text-sm">加载中...</div></Card>;
  }

  if (!data) {
    return <Card title="成本分解"><EmptyState title="暂无成本数据" /></Card>;
  }

  const agentEntries = dictToEntries(data.by_agent);
  const phaseEntries = dictToEntries(data.by_phase);
  const stepEntries = dictToEntries(data.by_step_type);

  return (
    <Card title="成本分解">
      {/* 汇总卡 */}
      <div className="flex gap-4 mb-4">
        <div className="flex items-center gap-2 px-3 py-1.5 bg-green-50 rounded-lg">
          <DollarSign className="w-4 h-4 text-green-600" />
          <div>
            <p className="text-xs text-gray-500">总成本</p>
            <p className="text-sm font-semibold text-gray-800">${data.total_cost.toFixed(4)}</p>
          </div>
        </div>
        <div className="flex items-center gap-2 px-3 py-1.5 bg-blue-50 rounded-lg">
          <Coins className="w-4 h-4 text-blue-600" />
          <div>
            <p className="text-xs text-gray-500">总 Token</p>
            <p className="text-sm font-semibold text-gray-800">{data.total_tokens.toLocaleString()}</p>
          </div>
        </div>
      </div>

      <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
        {/* by_agent 柱状 */}
        {agentEntries.length > 0 && (
          <Plot
            data={[{ type: 'bar', x: agentEntries.map(e => e[0]), y: agentEntries.map(e => e[1]), marker: { color: '#3b82f6' } }]}
            layout={{ title: '按 Agent', margin: { t: 30, b: 40, l: 40, r: 10 }, height: 220, paper_bgcolor: 'transparent' }}
            config={{ displayModeBar: false, responsive: true }}
            style={{ width: '100%' }}
          />
        )}

        {/* by_phase 饼图 */}
        {phaseEntries.length > 0 && (
          <Plot
            data={[{ type: 'pie', labels: phaseEntries.map(e => e[0]), values: phaseEntries.map(e => e[1]), hole: 0.4 }]}
            layout={{ title: '按阶段', margin: { t: 30, b: 20, l: 20, r: 20 }, height: 220, paper_bgcolor: 'transparent' }}
            config={{ displayModeBar: false, responsive: true }}
            style={{ width: '100%' }}
          />
        )}

        {/* by_step_type 柱状 */}
        {stepEntries.length > 0 && (
          <div className="md:col-span-2">
            <Plot
              data={[{ type: 'bar', x: stepEntries.map(e => e[0]), y: stepEntries.map(e => e[1]), marker: { color: '#8b5cf6' } }]}
              layout={{ title: '按步骤类型', margin: { t: 30, b: 60, l: 40, r: 10 }, height: 220, paper_bgcolor: 'transparent', xaxis: { tickangle: -30 } }}
              config={{ displayModeBar: false, responsive: true }}
              style={{ width: '100%' }}
            />
          </div>
        )}
      </div>
    </Card>
  );
}
