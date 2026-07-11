'use client';

import { useState } from 'react';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { Pill, Activity, Zap, X } from 'lucide-react';
import { getTreatments, optimizeTreatments, monitorEfficacy } from '@/lib/api';
import { useAppStore } from '@/lib/store';
import Card from '@/components/ui/Card';
import Button from '@/components/ui/Button';
import Badge from '@/components/ui/Badge';
import PlotlyChart from '@/components/charts/PlotlyChart';

export default function TreatmentsPage() {
  const { currentProject } = useAppStore();
  const queryClient = useQueryClient();
  const [monitorData, setMonitorData] = useState<any>(null);

  const { data: treatments, isLoading } = useQuery({
    queryKey: ['treatments', currentProject?.id],
    queryFn: () => getTreatments(currentProject?.id),
    enabled: !!currentProject,
  });

  const optimizeMutation = useMutation({
    mutationFn: () => optimizeTreatments(currentProject!.id),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ['treatments'] }),
  });

  const monitorMutation = useMutation({
    mutationFn: (id: string) => monitorEfficacy(id),
    onSuccess: (res) => {
      // 后端返回 StandardResponse(data=result)，解包
      setMonitorData((res as any)?.data || res);
    },
  });

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold">治疗方案</h1>
          <p className="text-sm text-gray-500 mt-1">个性化治疗组合优化 — 靶向/免疫/化疗/联合</p>
        </div>
        <Button onClick={() => optimizeMutation.mutate()} loading={optimizeMutation.isPending}>
          <Zap className="w-4 h-4" /> 优化组合
        </Button>
      </div>

      {isLoading ? (
        <div className="text-center py-12 text-gray-400">加载中...</div>
      ) : (
        <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
          {treatments?.map((t: any) => (
            <Card key={t.id}>
              <div className="space-y-3">
                <div className="flex items-start justify-between">
                  <div>
                    <div className="text-lg font-bold">{t.name}</div>
                    <div className="text-xs text-gray-500">{t.therapy_type}</div>
                  </div>
                  <Badge variant="status" value={t.status || 'planned'} />
                </div>

                <div className="grid grid-cols-3 gap-3 text-sm">
                  <div className="bg-emerald-50 p-2 rounded">
                    <div className="text-xs text-gray-500">疗效评分</div>
                    <div className="text-lg font-semibold text-emerald-700">
                      {t.efficacy_score != null ? t.efficacy_score.toFixed(2) : '—'}
                    </div>
                  </div>
                  <div className="bg-red-50 p-2 rounded">
                    <div className="text-xs text-gray-500">风险评分</div>
                    <div className="text-lg font-semibold text-red-700">
                      {t.risk_score != null ? t.risk_score.toFixed(2) : '—'}
                    </div>
                  </div>
                  <div className="bg-blue-50 p-2 rounded">
                    <div className="text-xs text-gray-500">置信度</div>
                    <div className="text-lg font-semibold text-blue-700">
                      {t.confidence != null ? (t.confidence * 100).toFixed(0) + '%' : '—'}
                    </div>
                  </div>
                </div>

                <div className="text-xs text-gray-500">
                  靶点：{(t.target_ids || []).length} 个 · 分子：{(t.molecule_ids || []).length} 个
                </div>

                <Button
                  size="sm"
                  variant="secondary"
                  loading={monitorMutation.isPending}
                  onClick={() => monitorMutation.mutate(t.id)}
                  className="w-full"
                >
                  <Activity className="w-3 h-3" /> 监测疗效
                </Button>
              </div>
            </Card>
          ))}
        </div>
      )}

      {(!treatments || treatments.length === 0) && !isLoading && (
        <Card>
          <div className="text-center py-12 text-gray-400">
            <Pill className="w-12 h-12 mx-auto mb-2 opacity-50" />
            暂无治疗方案，请点击"优化组合"
          </div>
        </Card>
      )}

      {/* 疗效监测弹窗 */}
      {monitorData && (
        <div className="fixed inset-0 bg-black/50 flex items-center justify-center z-50 p-4">
          <div className="bg-white rounded-lg max-w-2xl w-full max-h-[80vh] overflow-y-auto">
            <div className="flex items-center justify-between px-5 py-3 border-b">
              <h3 className="font-semibold">疗效监测</h3>
              <button onClick={() => setMonitorData(null)}>
                <X className="w-5 h-5 text-gray-400" />
              </button>
            </div>
            <div className="p-5 space-y-4">
              <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
                <div className="bg-gray-50 p-3 rounded">
                  <div className="text-xs text-gray-500">当前疗效</div>
                  <div className="text-lg font-semibold">{monitorData.current_efficacy?.toFixed(2) || '—'}</div>
                </div>
                <div className="bg-gray-50 p-3 rounded">
                  <div className="text-xs text-gray-500">趋势</div>
                  <div className="text-lg font-semibold">{monitorData.trend || '—'}</div>
                </div>
                <div className="bg-gray-50 p-3 rounded">
                  <div className="text-xs text-gray-500">不良事件</div>
                  <div className="text-lg font-semibold">
                    {Array.isArray(monitorData.adverse_events) ? monitorData.adverse_events.length : (monitorData.adverse_events || 0)}
                  </div>
                </div>
                <div className="bg-gray-50 p-3 rounded">
                  <div className="text-xs text-gray-500">实验数</div>
                  <div className="text-lg font-semibold">{monitorData.experiments_count || 0}</div>
                </div>
              </div>
              <div className="bg-yellow-50 border border-yellow-200 p-3 rounded text-sm">
                <strong>建议：</strong>{monitorData.recommendation || '继续监测'}
              </div>
              <pre className="bg-gray-900 text-gray-100 p-3 rounded text-xs overflow-x-auto">
                {JSON.stringify(monitorData, null, 2)}
              </pre>
            </div>
          </div>
        </div>
      )}

      {/* 优化结果 */}
      {optimizeMutation.data && (
        <Card title="优化结果">
          <pre className="bg-gray-900 text-gray-100 p-4 rounded text-xs overflow-x-auto">
            {JSON.stringify((optimizeMutation.data as any)?.data || optimizeMutation.data, null, 2)}
          </pre>
        </Card>
      )}
    </div>
  );
}
