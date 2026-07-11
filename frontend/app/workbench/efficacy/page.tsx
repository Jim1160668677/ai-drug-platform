'use client';

import { useQuery } from '@tanstack/react-query';
import { Activity, TrendingUp, TrendingDown, AlertCircle } from 'lucide-react';
import { getEfficacySummary, getEfficacyRecords } from '@/lib/api';
import { useAppStore } from '@/lib/store';
import Card from '@/components/ui/Card';
import Badge from '@/components/ui/Badge';

export default function EfficacyPage() {
  const { currentProject } = useAppStore();

  const { data: summary, isLoading: summaryLoading } = useQuery({
    queryKey: ['efficacy-summary', currentProject?.id],
    queryFn: () => getEfficacySummary(currentProject?.id),
    enabled: !!currentProject,
  });

  const { data: recordsData, isLoading: recordsLoading } = useQuery({
    queryKey: ['efficacy-records', currentProject?.id],
    queryFn: () => getEfficacyRecords({ project_id: currentProject?.id, limit: 50 }),
    enabled: !!currentProject,
  });

  const summaryData: any = (summary as any)?.data || summary || {};
  const records: any[] = (recordsData as any)?.data?.items || (recordsData as any)?.data || recordsData || [];

  const statCards = [
    {
      label: '客观缓解率 (ORR)',
      value: summaryData.overall_orr != null ? `${(summaryData.overall_orr * 100).toFixed(1)}%` : '-',
      icon: TrendingUp,
      color: 'text-green-500',
    },
    {
      label: '疾病控制率 (DCR)',
      value: summaryData.overall_dcr != null ? `${(summaryData.overall_dcr * 100).toFixed(1)}%` : '-',
      icon: Activity,
      color: 'text-blue-500',
    },
    {
      label: '中位 PFS (天)',
      value: summaryData.median_pfs_days != null ? summaryData.median_pfs_days : '-',
      icon: TrendingDown,
      color: 'text-purple-500',
    },
    {
      label: '中位 OS (天)',
      value: summaryData.median_os_days != null ? summaryData.median_os_days : '-',
      icon: TrendingUp,
      color: 'text-orange-500',
    },
  ];

  const RECIST_VARIANT: Record<string, 'green' | 'blue' | 'gray' | 'red'> = {
    CR: 'green',
    PR: 'blue',
    SD: 'gray',
    PD: 'red',
  };

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-2xl font-bold flex items-center gap-2">
          <Activity className="w-6 h-6" /> 疗效监测
        </h1>
        <p className="text-sm text-gray-500 mt-1">
          RECIST 1.1 标准化疗效评估 + ORR/DCR/Kaplan-Meier 生存分析 + CTCAE v5.0 不良事件
        </p>
      </div>

      {!currentProject ? (
        <Card className="p-8 text-center text-gray-500">
          <AlertCircle className="w-12 h-12 mx-auto mb-4 text-gray-300" />
          <p>请先选择项目</p>
        </Card>
      ) : summaryLoading ? (
        <Card className="p-8 text-center text-gray-500">加载汇总数据...</Card>
      ) : (
        <>
          <div className="grid grid-cols-1 md:grid-cols-4 gap-4">
            {statCards.map((stat) => {
              const Icon = stat.icon;
              return (
                <Card key={stat.label} className="p-5">
                  <div className="flex items-center justify-between mb-2">
                    <span className="text-sm text-gray-500">{stat.label}</span>
                    <Icon className={`w-5 h-5 ${stat.color}`} />
                  </div>
                  <p className="text-2xl font-bold">{stat.value}</p>
                </Card>
              );
            })}
          </div>

          {summaryData.by_target && Object.keys(summaryData.by_target).length > 0 && (
            <Card className="p-5">
              <h3 className="font-semibold mb-3">按靶点分组</h3>
              <div className="overflow-x-auto">
                <table className="w-full text-sm">
                  <thead>
                    <tr className="border-b text-left text-gray-500">
                      <th className="pb-2">靶点</th>
                      <th className="pb-2">样本数</th>
                      <th className="pb-2">ORR</th>
                      <th className="pb-2">DCR</th>
                    </tr>
                  </thead>
                  <tbody>
                    {Object.entries(summaryData.by_target).map(([target, stats]: [string, any]) => (
                      <tr key={target} className="border-b">
                        <td className="py-2 font-medium">{target}</td>
                        <td className="py-2">{stats.count}</td>
                        <td className="py-2">{(stats.orr * 100).toFixed(1)}%</td>
                        <td className="py-2">{(stats.dcr * 100).toFixed(1)}%</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </Card>
          )}

          <Card className="p-5">
            <h3 className="font-semibold mb-3">疗效记录</h3>
            {recordsLoading ? (
              <p className="text-center text-gray-500 py-4">加载记录...</p>
            ) : records.length === 0 ? (
              <p className="text-center text-gray-500 py-4">暂无疗效记录</p>
            ) : (
              <div className="overflow-x-auto">
                <table className="w-full text-sm">
                  <thead>
                    <tr className="border-b text-left text-gray-500">
                      <th className="pb-2">记录 ID</th>
                      <th className="pb-2">RECIST 响应</th>
                      <th className="pb-2">随访天数</th>
                      <th className="pb-2">不良事件</th>
                      <th className="pb-2">创建时间</th>
                    </tr>
                  </thead>
                  <tbody>
                    {records.map((rec: any) => (
                      <tr key={rec.id} className="border-b">
                        <td className="py-2 font-mono text-xs">{rec.id?.slice(0, 8)}</td>
                        <td className="py-2">
                          {rec.recist_response && (
                            <Badge variant={RECIST_VARIANT[rec.recist_response] || 'gray'}>
                              {rec.recist_response}
                            </Badge>
                          )}
                        </td>
                        <td className="py-2">{rec.follow_up_days || '-'}</td>
                        <td className="py-2">
                          {rec.adverse_events?.length > 0 ? (
                            <Badge variant="red">{rec.adverse_events.length} 项</Badge>
                          ) : (
                            <span className="text-gray-400">无</span>
                          )}
                        </td>
                        <td className="py-2 text-xs">
                          {rec.created_at ? new Date(rec.created_at).toLocaleString() : '-'}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </Card>
        </>
      )}
    </div>
  );
}
