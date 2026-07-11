'use client';

import { useState } from 'react';
import { useMutation } from '@tanstack/react-query';
import { FileText, Download, Database, BarChart3, Database as DBIcon, Target as TargetIcon, GitBranch, FlaskConical } from 'lucide-react';
import { exportSDTM, exportADaM, getProjectSummary, getProjects } from '@/lib/api';
import { useQuery } from '@tanstack/react-query';
import { useAppStore } from '@/lib/store';
import Card from '@/components/ui/Card';
import Button from '@/components/ui/Button';
import PlotlyChart from '@/components/charts/PlotlyChart';

export default function ReportsPage() {
  const { currentProject } = useAppStore();
  const [sdtmData, setSdtmData] = useState<any>(null);
  const [adamData, setAdamData] = useState<any>(null);
  const [csvContent, setCsvContent] = useState<string>('');

  const { data: projects } = useQuery({ queryKey: ['projects'], queryFn: getProjects });
  const projectId = currentProject?.id || projects?.[0]?.id;

  const { data: summary, refetch: refetchSummary } = useQuery({
    queryKey: ['project-summary', projectId],
    queryFn: () => getProjectSummary(projectId!),
    enabled: !!projectId,
  });

  const sdtmMutation = useMutation({
    mutationFn: () => exportSDTM(projectId!),
    onSuccess: (res) => {
      const data = res?.data || res;
      setSdtmData(data);
      setCsvContent(data.csv || '');
    },
  });

  const adamMutation = useMutation({
    mutationFn: () => exportADaM(projectId!),
    onSuccess: (res) => {
      setAdamData(res?.data || res);
    },
  });

  const downloadCSV = () => {
    if (!csvContent) return;
    const blob = new Blob([csvContent], { type: 'text/csv;charset=utf-8' });
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = `sdtm_${projectId}.csv`;
    a.click();
    URL.revokeObjectURL(url);
  };

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-2xl font-bold">报告中心</h1>
        <p className="text-sm text-gray-500 mt-1">CDISC SDTM/ADaM 标准导出 + 项目摘要</p>
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
        {/* SDTM 导出 */}
        <Card
          title="SDTM 导出"
          action={
            <Button
              size="sm"
              onClick={() => sdtmMutation.mutate()}
              loading={sdtmMutation.isPending}
              disabled={!projectId}
            >
              <Database className="w-3 h-3" /> 生成
            </Button>
          }
        >
          {sdtmData?.domains ? (
            <div className="space-y-3">
              <div className="flex gap-2 flex-wrap">
                {Object.keys(sdtmData.domains).map((d) => (
                  <span key={d} className="px-2 py-0.5 bg-primary-100 text-primary-800 rounded text-xs font-medium">
                    {d}
                  </span>
                ))}
              </div>
              {Object.entries(sdtmData.domains).map(([domain, rows]: any) => (
                <div key={domain}>
                  <div className="text-xs font-semibold text-gray-700 mb-1">
                    {domain} ({rows.length} 条)
                  </div>
                  <div className="overflow-x-auto border border-gray-200 rounded">
                    <table className="w-full text-xs">
                      <thead className="bg-gray-50">
                        <tr>
                          {rows[0] && Object.keys(rows[0]).map((k) => (
                            <th key={k} className="px-2 py-1 text-left border-b">{k}</th>
                          ))}
                        </tr>
                      </thead>
                      <tbody>
                        {rows.slice(0, 5).map((r: any, i: number) => (
                          <tr key={i} className="border-b border-gray-100">
                            {Object.values(r).map((v: any, j: number) => (
                              <td key={j} className="px-2 py-1">{String(v ?? '—')}</td>
                            ))}
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                  {rows.length > 5 && (
                    <div className="text-xs text-gray-400 mt-1">显示前 5 条，共 {rows.length} 条</div>
                  )}
                </div>
              ))}
              <Button size="sm" variant="secondary" onClick={downloadCSV}>
                <Download className="w-3 h-3" /> 下载 CSV
              </Button>
            </div>
          ) : (
            <div className="text-center py-8 text-gray-400 text-sm">
              点击"生成"导出 SDTM 域（DM/VS/RS/EX/SV）
            </div>
          )}
        </Card>

        {/* ADaM 导出 */}
        <Card
          title="ADaM 导出"
          action={
            <Button
              size="sm"
              onClick={() => adamMutation.mutate()}
              loading={adamMutation.isPending}
              disabled={!projectId}
            >
              <BarChart3 className="w-3 h-3" /> 生成
            </Button>
          }
        >
          {adamData?.datasets ? (
            <div className="space-y-3">
              {Object.entries(adamData.datasets).map(([ds, rows]: any) => (
                <div key={ds}>
                  <div className="text-xs font-semibold text-gray-700 mb-1">
                    {ds} ({rows.length} 条)
                  </div>
                  <div className="overflow-x-auto border border-gray-200 rounded">
                    <table className="w-full text-xs">
                      <thead className="bg-gray-50">
                        <tr>
                          {rows[0] && Object.keys(rows[0]).map((k) => (
                            <th key={k} className="px-2 py-1 text-left border-b">{k}</th>
                          ))}
                        </tr>
                      </thead>
                      <tbody>
                        {rows.slice(0, 5).map((r: any, i: number) => (
                          <tr key={i} className="border-b border-gray-100">
                            {Object.values(r).map((v: any, j: number) => (
                              <td key={j} className="px-2 py-1">{String(v ?? '—')}</td>
                            ))}
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                </div>
              ))}
            </div>
          ) : (
            <div className="text-center py-8 text-gray-400 text-sm">
              点击"生成"派生 ADaM 数据集（ADSL/ADRS/ADAE）
            </div>
          )}
        </Card>
      </div>

      {/* 项目摘要看板 */}
      <Card title="项目摘要看板" action={
        <Button size="sm" variant="secondary" onClick={() => refetchSummary()} disabled={!projectId}>
          <FileText className="w-3 h-3" /> 刷新
        </Button>
      }>
        {(() => {
          const s = (summary as any)?.data || summary;
          if (!s) {
            return (
              <div className="text-center py-8 text-gray-400 text-sm">
                <FileText className="w-12 h-12 mx-auto mb-2 opacity-50" />
                {!projectId ? '请先选择项目' : '点击"刷新"加载项目摘要'}
              </div>
            );
          }
          const datasets = s.datasets || { total: 0, by_type: {} };
          const targets = s.targets || { total: 0, by_grade: {} };
          const hyps = s.hypotheses || { total: 0, completed: 0 };
          const exps = s.experiments || { total: 0, successful: 0 };
          const hypPct = hyps.total > 0 ? Math.round((hyps.completed / hyps.total) * 100) : 0;
          const expPct = exps.total > 0 ? Math.round((exps.successful / exps.total) * 100) : 0;

          const gradeEntries = Object.entries(targets.by_grade || {});
          const typeEntries = Object.entries(datasets.by_type || {});

          return (
            <div className="space-y-4">
              {/* 4 个统计卡片 */}
              <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
                <div className="bg-blue-50 border border-blue-100 rounded-lg p-3">
                  <div className="flex items-center gap-2 text-blue-700">
                    <DBIcon className="w-4 h-4" />
                    <span className="text-xs font-medium">数据集</span>
                  </div>
                  <div className="mt-1 text-2xl font-bold text-blue-900">{datasets.total}</div>
                  <div className="text-xs text-blue-600 mt-0.5">
                    {typeEntries.length} 种类型
                  </div>
                </div>
                <div className="bg-purple-50 border border-purple-100 rounded-lg p-3">
                  <div className="flex items-center gap-2 text-purple-700">
                    <TargetIcon className="w-4 h-4" />
                    <span className="text-xs font-medium">靶点</span>
                  </div>
                  <div className="mt-1 text-2xl font-bold text-purple-900">{targets.total}</div>
                  <div className="text-xs text-purple-600 mt-0.5">
                    {gradeEntries.length} 个分级
                  </div>
                </div>
                <div className="bg-amber-50 border border-amber-100 rounded-lg p-3">
                  <div className="flex items-center gap-2 text-amber-700">
                    <GitBranch className="w-4 h-4" />
                    <span className="text-xs font-medium">假设</span>
                  </div>
                  <div className="mt-1 text-2xl font-bold text-amber-900">{hyps.total}</div>
                  <div className="text-xs text-amber-600 mt-0.5">
                    已完成 {hyps.completed}/{hyps.total}
                  </div>
                </div>
                <div className="bg-emerald-50 border border-emerald-100 rounded-lg p-3">
                  <div className="flex items-center gap-2 text-emerald-700">
                    <FlaskConical className="w-4 h-4" />
                    <span className="text-xs font-medium">实验</span>
                  </div>
                  <div className="mt-1 text-2xl font-bold text-emerald-900">{exps.total}</div>
                  <div className="text-xs text-emerald-600 mt-0.5">
                    成功 {exps.successful}/{exps.total}
                  </div>
                </div>
              </div>

              {/* 进度条 */}
              <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                <div className="bg-gray-50 rounded-lg p-3">
                  <div className="flex justify-between text-xs mb-1">
                    <span className="font-medium text-gray-700">假设完成度</span>
                    <span className="text-gray-500">{hyps.completed}/{hyps.total} ({hypPct}%)</span>
                  </div>
                  <div className="w-full bg-gray-200 rounded-full h-2 overflow-hidden">
                    <div
                      className="bg-amber-500 h-full rounded-full transition-all"
                      style={{ width: `${hypPct}%` }}
                    />
                  </div>
                </div>
                <div className="bg-gray-50 rounded-lg p-3">
                  <div className="flex justify-between text-xs mb-1">
                    <span className="font-medium text-gray-700">实验成功率</span>
                    <span className="text-gray-500">{exps.successful}/{exps.total} ({expPct}%)</span>
                  </div>
                  <div className="w-full bg-gray-200 rounded-full h-2 overflow-hidden">
                    <div
                      className="bg-emerald-500 h-full rounded-full transition-all"
                      style={{ width: `${expPct}%` }}
                    />
                  </div>
                </div>
              </div>

              {/* 分布图表 */}
              <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                {gradeEntries.length > 0 && (
                  <div>
                    <div className="text-xs font-semibold text-gray-700 mb-2">靶点分级分布</div>
                    <PlotlyChart
                      data={[{
                        type: 'bar',
                        x: gradeEntries.map(([g]) => `Grade ${g}`),
                        y: gradeEntries.map(([, v]: any) => v),
                        marker: { color: ['#16a34a', '#2563eb', '#d97706', '#dc2626', '#6b7280'] },
                        text: gradeEntries.map(([, v]: any) => String(v)),
                        textposition: 'auto',
                      }]}
                      layout={{
                        margin: { t: 20, b: 40, l: 30, r: 10 },
                        height: 220,
                        yaxis: { title: { text: '数量' }, dtick: 1 },
                        xaxis: { title: { text: '证据分级' } },
                      }}
                    />
                  </div>
                )}
                {typeEntries.length > 0 && (
                  <div>
                    <div className="text-xs font-semibold text-gray-700 mb-2">数据集类型分布</div>
                    <PlotlyChart
                      data={[{
                        type: 'pie',
                        labels: typeEntries.map(([t]) => t),
                        values: typeEntries.map(([, v]: any) => v),
                        hole: 0.4,
                        textinfo: 'label+value',
                        marker: { colors: ['#2563eb', '#16a34a', '#d97706', '#9333ea', '#0891b2'] },
                      }]}
                      layout={{
                        margin: { t: 10, b: 10, l: 10, r: 10 },
                        height: 220,
                        showlegend: true,
                        legend: { font: { size: 10 } },
                      }}
                    />
                  </div>
                )}
              </div>
            </div>
          );
        })()}
      </Card>
    </div>
  );
}
