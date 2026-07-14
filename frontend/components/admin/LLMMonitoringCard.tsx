'use client';

import { useState } from 'react';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { Activity, DollarSign, Zap, AlertCircle, Trash2, RefreshCw } from 'lucide-react';
import { getLLMMetrics, getCacheStats, invalidateCache } from '@/lib/api';
import { toast } from '@/lib/notification';
import Card from '@/components/ui/Card';
import Button from '@/components/ui/Button';
import Badge from '@/components/ui/Badge';

export default function LLMMonitoringCard() {
  const queryClient = useQueryClient();
  const [days, setDays] = useState(7);

  const { data: metrics, isLoading } = useQuery({
    queryKey: ['llm-metrics', days],
    queryFn: () => getLLMMetrics(days),
    refetchInterval: 30000,
  });

  const { data: cacheStats } = useQuery({
    queryKey: ['llm-cache-stats'],
    queryFn: () => getCacheStats(),
    refetchInterval: 15000,
  });

  const invalidateMutation = useMutation({
    mutationFn: () => invalidateCache(),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['llm-cache-stats'] });
      toast.success('缓存已清空', 'LLM 响应缓存已全部失效');
    },
    onError: () => toast.error('操作失败', '请检查权限'),
  });

  if (isLoading) {
    return <Card><div className="text-center py-12 text-gray-400">加载监控数据...</div></Card>;
  }

  const summary = metrics?.summary || {};
  const todayCost = metrics?.today_cost || {};
  const timeline = metrics?.timeline || [];
  const byModel = metrics?.by_model || [];
  const byTier = metrics?.by_tier || [];
  const errors = metrics?.recent_errors || [];

  return (
    <div className="space-y-4">
      {/* 概览卡片 */}
      <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
        <Card className="p-4">
          <div className="flex items-center gap-2 text-blue-600">
            <Zap className="w-4 h-4" />
            <span className="text-xs font-medium">总调用</span>
          </div>
          <p className="text-2xl font-bold mt-1">{summary.total_calls || 0}</p>
          <p className="text-xs text-gray-400 mt-0.5">{days} 天</p>
        </Card>
        <Card className="p-4">
          <div className="flex items-center gap-2 text-green-600">
            <Activity className="w-4 h-4" />
            <span className="text-xs font-medium">成功率</span>
          </div>
          <p className="text-2xl font-bold mt-1">{((summary.success_rate || 0) * 100).toFixed(1)}%</p>
          <p className="text-xs text-gray-400 mt-0.5">{summary.success_calls || 0} 成功</p>
        </Card>
        <Card className="p-4">
          <div className="flex items-center gap-2 text-amber-600">
            <DollarSign className="w-4 h-4" />
            <span className="text-xs font-medium">总成本</span>
          </div>
          <p className="text-2xl font-bold mt-1">${(summary.total_cost_usd || 0).toFixed(4)}</p>
          <p className="text-xs text-gray-400 mt-0.5">{summary.total_tokens || 0} tokens</p>
        </Card>
        <Card className="p-4">
          <div className="flex items-center gap-2 text-purple-600">
            <RefreshCw className="w-4 h-4" />
            <span className="text-xs font-medium">缓存命中</span>
          </div>
          <p className="text-2xl font-bold mt-1">{((cacheStats?.hit_rate || 0) * 100).toFixed(1)}%</p>
          <p className="text-xs text-gray-400 mt-0.5">{cacheStats?.hits || 0} 命中 / {cacheStats?.misses || 0} 未命中</p>
        </Card>
      </div>

      {/* 今日成本 */}
      <Card className="p-4">
        <h3 className="text-sm font-semibold mb-3">今日成本追踪</h3>
        <div className="grid grid-cols-3 gap-3 text-sm">
          <div>
            <p className="text-xs text-gray-400">已花费</p>
            <p className="font-bold text-red-600">${(todayCost.spent_usd || 0).toFixed(4)}</p>
          </div>
          <div>
            <p className="text-xs text-gray-400">日预算</p>
            <p className="font-bold">${(todayCost.budget_usd || 0).toFixed(2)}</p>
          </div>
          <div>
            <p className="text-xs text-gray-400">利用率</p>
            <p className="font-bold text-amber-600">{((todayCost.utilization || 0) * 100).toFixed(1)}%</p>
          </div>
        </div>
        <div className="mt-2 w-full bg-gray-200 rounded-full h-2">
          <div
            className="h-full rounded-full bg-amber-500 transition-all"
            style={{ width: `${Math.min((todayCost.utilization || 0) * 100, 100)}%` }}
          />
        </div>
      </Card>

      {/* 每日趋势 */}
      {timeline.length > 0 && (
        <Card className="p-4">
          <h3 className="text-sm font-semibold mb-3">每日调用趋势</h3>
          <div className="space-y-1">
            {timeline.map((t: any) => (
              <div key={t.date} className="flex items-center gap-3 text-xs">
                <span className="w-24 text-gray-500">{t.date}</span>
                <div className="flex-1 bg-gray-100 rounded-full h-4 relative">
                  <div
                    className="h-full rounded-full bg-blue-500"
                    style={{ width: `${Math.min((t.calls / Math.max(...timeline.map((x: any) => x.calls))) * 100, 100)}%` }}
                  />
                </div>
                <span className="w-8 text-right font-medium">{t.calls}</span>
                <span className="w-16 text-right text-gray-400">${(t.cost_usd || 0).toFixed(3)}</span>
              </div>
            ))}
          </div>
        </Card>
      )}

      {/* 按模型统计 */}
      {byModel.length > 0 && (
        <Card className="p-4">
          <h3 className="text-sm font-semibold mb-3">按模型统计</h3>
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="text-xs text-gray-400 border-b">
                  <th className="text-left py-2">模型</th>
                  <th className="text-right py-2">调用次数</th>
                  <th className="text-right py-2">成本</th>
                  <th className="text-right py-2">Tokens</th>
                </tr>
              </thead>
              <tbody>
                {byModel.map((m: any) => (
                  <tr key={m.model} className="border-b border-gray-50">
                    <td className="py-2 font-mono text-xs">{m.model}</td>
                    <td className="text-right">{m.calls}</td>
                    <td className="text-right">${(m.cost_usd || 0).toFixed(4)}</td>
                    <td className="text-right">{m.tokens || 0}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </Card>
      )}

      {/* 最近错误 */}
      {errors.length > 0 && (
        <Card className="p-4">
          <h3 className="text-sm font-semibold mb-3 flex items-center gap-2">
            <AlertCircle className="w-4 h-4 text-red-500" />
            最近错误
          </h3>
          <div className="space-y-2">
            {errors.slice(0, 5).map((e: any) => (
              <div key={e.id} className="text-xs bg-red-50 rounded p-2">
                <div className="flex items-center gap-2">
                  <Badge variant="danger">{e.tier}</Badge>
                  <span className="font-mono">{e.model}</span>
                  <span className="text-gray-400 ml-auto">{e.created_at?.slice(0, 19)}</span>
                </div>
                <p className="mt-1 text-gray-600 truncate">{e.error}</p>
              </div>
            ))}
          </div>
        </Card>
      )}

      {/* 缓存管理 */}
      <Card className="p-4">
        <div className="flex items-center justify-between mb-3">
          <h3 className="text-sm font-semibold">缓存管理</h3>
          <Button
            size="sm"
            variant="ghost"
            loading={invalidateMutation.isPending}
            onClick={() => invalidateMutation.mutate()}
            className="text-red-600 hover:bg-red-50"
          >
            <Trash2 className="w-3 h-3" /> 清空缓存
          </Button>
        </div>
        <div className="grid grid-cols-3 gap-3 text-sm">
          <div>
            <p className="text-xs text-gray-400">内存条目</p>
            <p className="font-medium">{cacheStats?.memory_entries || 0} / {cacheStats?.max_size || 0}</p>
          </div>
          <div>
            <p className="text-xs text-gray-400">命中率</p>
            <p className="font-medium text-green-600">{((cacheStats?.hit_rate || 0) * 100).toFixed(1)}%</p>
          </div>
          <div>
            <p className="text-xs text-gray-400">默认 TTL</p>
            <p className="font-medium">{cacheStats?.default_ttl_sec || 0}s</p>
          </div>
        </div>
      </Card>
    </div>
  );
}
