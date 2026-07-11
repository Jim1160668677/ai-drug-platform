'use client';

import { useEffect } from 'react';
import { useRouter } from 'next/navigation';
import Link from 'next/link';
import { useQuery } from '@tanstack/react-query';
import {
  FolderKanban,
  Database,
  Target,
  Atom,
  GitBranch,
  FlaskConical,
  Pill,
  Activity,
  TrendingUp,
  CheckCircle2,
  AlertCircle,
} from 'lucide-react';
import { getDashboardOverview } from '@/lib/api';
import { getCurrentUser, isLoggedIn } from '@/lib/auth';
import { useAppStore } from '@/lib/store';
import Card from '@/components/ui/Card';
import Badge from '@/components/ui/Badge';
import Button from '@/components/ui/Button';
import PlotlyChart from '@/components/charts/PlotlyChart';

export default function DashboardPage() {
  const router = useRouter();
  const { setProject } = useAppStore();

  useEffect(() => {
    if (!isLoggedIn()) {
      router.replace('/');
    }
  }, [router]);

  const { data, isLoading, error } = useQuery({
    queryKey: ['dashboard-overview'],
    queryFn: getDashboardOverview,
    enabled: isLoggedIn(),
  });

  if (!isLoggedIn()) {
    return null;
  }

  const user = getCurrentUser();
  const overview = (data as any)?.data || data;

  if (isLoading) {
    return (
      <div className="flex items-center justify-center min-h-[60vh]">
        <div className="text-center">
          <Activity className="w-10 h-10 mx-auto mb-3 text-primary-500 animate-pulse" />
          <div className="text-sm text-gray-500">加载全局看板...</div>
        </div>
      </div>
    );
  }

  if (error || !overview) {
    return (
      <div className="flex items-center justify-center min-h-[60vh]">
        <Card className="max-w-md">
          <div className="text-center py-6">
            <AlertCircle className="w-12 h-12 mx-auto mb-3 text-red-500" />
            <h2 className="text-lg font-semibold">加载失败</h2>
            <p className="text-sm text-gray-500 mt-2">
              无法获取全局看板数据，请确认后端服务正常
            </p>
          </div>
        </Card>
      </div>
    );
  }

  const g = overview.global || {};
  const byCancerType = overview.by_cancer_type || {};
  const byStatus = overview.by_status || {};
  const projects = overview.projects || [];
  const recentExperiments = overview.recent_experiments || [];

  const kpiCards = [
    { label: '项目数', value: g.projects ?? 0, icon: FolderKanban, color: 'text-blue-600 bg-blue-50' },
    { label: '数据集', value: g.datasets ?? 0, icon: Database, color: 'text-emerald-600 bg-emerald-50' },
    { label: '靶点', value: g.targets ?? 0, icon: Target, color: 'text-purple-600 bg-purple-50' },
    { label: '分子', value: g.molecules ?? 0, icon: Atom, color: 'text-pink-600 bg-pink-50' },
    { label: '假设', value: g.hypotheses ?? 0, icon: GitBranch, color: 'text-indigo-600 bg-indigo-50' },
    { label: '实验', value: g.experiments ?? 0, icon: FlaskConical, color: 'text-amber-600 bg-amber-50' },
    { label: '治疗方案', value: g.treatments ?? 0, icon: Pill, color: 'text-rose-600 bg-rose-50' },
  ];

  // 进入项目工作台
  const enterProject = (p: any) => {
    setProject({
      id: p.id,
      name: p.name,
      cancer_type: p.cancer_type,
      stage: p.stage,
      status: p.status,
    });
    router.push('/workbench');
  };

  return (
    <div className="space-y-6">
      {/* 页面标题 */}
      <div className="flex items-start justify-between flex-wrap gap-3">
        <div>
          <h1 className="text-2xl font-bold text-gray-900">全局看板</h1>
          <p className="text-sm text-gray-500 mt-1">
            跨项目统计 · 资源总览 · 最近活动 — 欢迎，{user?.name || '研究者'}
          </p>
        </div>
        <Link href="/workbench" prefetch={false}>
          <Button variant="primary">
            <TrendingUp className="w-4 h-4" /> 进入工作台
          </Button>
        </Link>
      </div>

      {/* KPI 卡片 */}
      <div className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-7 gap-3">
        {kpiCards.map((k) => {
          const Icon = k.icon;
          return (
            <Card key={k.label}>
              <div className="flex flex-col items-center text-center">
                <div className={`w-10 h-10 rounded-lg flex items-center justify-center mb-2 ${k.color}`}>
                  <Icon className="w-5 h-5" />
                </div>
                <div className="text-2xl font-bold text-gray-900">{k.value}</div>
                <div className="text-xs text-gray-500 mt-0.5">{k.label}</div>
              </div>
            </Card>
          );
        })}
      </div>

      {/* 关键率 + 图表 */}
      <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
        {/* 关键率 */}
        <Card title="关键率">
          <div className="space-y-5">
            <div>
              <div className="flex items-baseline justify-between mb-1">
                <span className="text-sm text-gray-600">假设完成度</span>
                <span className="text-sm font-semibold">
                  {g.completed_hypotheses ?? 0} / {g.hypotheses ?? 0}
                </span>
              </div>
              <div className="w-full h-2 bg-gray-100 rounded-full overflow-hidden">
                <div
                  className="h-full bg-indigo-500 rounded-full transition-all"
                  style={{ width: `${(g.hypothesis_completion_rate ?? 0) * 100}%` }}
                />
              </div>
              <div className="text-xs text-gray-400 mt-1">
                {Math.round((g.hypothesis_completion_rate ?? 0) * 100)}%
              </div>
            </div>

            <div>
              <div className="flex items-baseline justify-between mb-1">
                <span className="text-sm text-gray-600">实验成功率</span>
                <span className="text-sm font-semibold">
                  {g.successful_experiments ?? 0} / {g.experiments ?? 0}
                </span>
              </div>
              <div className="w-full h-2 bg-gray-100 rounded-full overflow-hidden">
                <div
                  className="h-full bg-emerald-500 rounded-full transition-all"
                  style={{ width: `${(g.experiment_success_rate ?? 0) * 100}%` }}
                />
              </div>
              <div className="text-xs text-gray-400 mt-1">
                {Math.round((g.experiment_success_rate ?? 0) * 100)}%
              </div>
            </div>

            <div className="pt-3 border-t border-gray-100 grid grid-cols-2 gap-3">
              <div className="text-center">
                <CheckCircle2 className="w-5 h-5 mx-auto text-emerald-500 mb-1" />
                <div className="text-lg font-bold">{g.completed_hypotheses ?? 0}</div>
                <div className="text-xs text-gray-500">已完成假设</div>
              </div>
              <div className="text-center">
                <CheckCircle2 className="w-5 h-5 mx-auto text-emerald-500 mb-1" />
                <div className="text-lg font-bold">{g.successful_experiments ?? 0}</div>
                <div className="text-xs text-gray-500">成功实验</div>
              </div>
            </div>
          </div>
        </Card>

        {/* 癌种分布 */}
        <Card title="癌种分布">
          {Object.keys(byCancerType).length > 0 ? (
            <PlotlyChart
              data={[
                {
                  type: 'pie',
                  labels: Object.keys(byCancerType),
                  values: Object.values(byCancerType),
                  textinfo: 'label+value+percent',
                  hole: 0.4,
                  marker: { colors: ['#3b82f6', '#10b981', '#f59e0b', '#ef4444', '#8b5cf6', '#ec4899'] },
                },
              ]}
              layout={{ margin: { t: 10, b: 10, l: 10, r: 10 }, height: 260, showlegend: false }}
            />
          ) : (
            <div className="text-center text-sm text-gray-400 py-12">暂无数据</div>
          )}
        </Card>

        {/* 项目状态分布 */}
        <Card title="项目状态分布">
          {Object.keys(byStatus).length > 0 ? (
            <PlotlyChart
              data={[
                {
                  type: 'bar',
                  x: Object.keys(byStatus),
                  y: Object.values(byStatus) as any[],
                  marker: { color: ['#10b981', '#f59e0b', '#3b82f6', '#94a3b8'] },
                  text: Object.values(byStatus),
                  textposition: 'auto',
                },
              ]}
              layout={{
                margin: { t: 20, b: 40, l: 40, r: 20 },
                height: 260,
                xaxis: { title: { text: '' } },
                yaxis: { title: { text: '项目数' }, dtick: 1 },
              }}
            />
          ) : (
            <div className="text-center text-sm text-gray-400 py-12">暂无数据</div>
          )}
        </Card>
      </div>

      {/* 项目列表 */}
      <Card title={`项目明细 (${projects.length})`} action={<FolderKanban className="w-4 h-4 text-gray-400" />}>
        {projects.length > 0 ? (
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b border-gray-200 text-gray-500">
                  <th className="text-left py-2 px-3">项目</th>
                  <th className="text-left py-2 px-3">癌种/分期</th>
                  <th className="text-left py-2 px-3">状态</th>
                  <th className="text-center py-2 px-2">数据集</th>
                  <th className="text-center py-2 px-2">靶点</th>
                  <th className="text-center py-2 px-2">分子</th>
                  <th className="text-center py-2 px-2">假设</th>
                  <th className="text-center py-2 px-2">实验</th>
                  <th className="text-center py-2 px-2">治疗</th>
                  <th className="text-right py-2 px-3">操作</th>
                </tr>
              </thead>
              <tbody>
                {projects.map((p: any) => (
                  <tr key={p.id} className="border-b border-gray-100 hover:bg-gray-50">
                    <td className="py-2 px-3">
                      <div className="font-medium text-gray-800">{p.name}</div>
                      {p.patient_pseudonym && (
                        <div className="text-xs text-gray-400 font-mono">{p.patient_pseudonym}</div>
                      )}
                    </td>
                    <td className="py-2 px-3">
                      <div>{p.cancer_type || '—'}</div>
                      <div className="text-xs text-gray-400">{p.stage || '—'}</div>
                    </td>
                    <td className="py-2 px-3">
                      <Badge variant="status" value={p.status} />
                    </td>
                    <td className="py-2 px-2 text-center">{p.counts?.datasets ?? 0}</td>
                    <td className="py-2 px-2 text-center">{p.counts?.targets ?? 0}</td>
                    <td className="py-2 px-2 text-center">{p.counts?.molecules ?? 0}</td>
                    <td className="py-2 px-2 text-center">{p.counts?.hypotheses ?? 0}</td>
                    <td className="py-2 px-2 text-center">{p.counts?.experiments ?? 0}</td>
                    <td className="py-2 px-2 text-center">{p.counts?.treatments ?? 0}</td>
                    <td className="py-2 px-3 text-right">
                      <Button variant="ghost" onClick={() => enterProject(p)}>
                        进入
                      </Button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        ) : (
          <div className="text-center text-sm text-gray-400 py-12">暂无项目，请先创建</div>
        )}
      </Card>

      {/* 最近活动 */}
      <Card title={`最近活动 (${recentExperiments.length})`} action={<Activity className="w-4 h-4 text-gray-400" />}>
        {recentExperiments.length > 0 ? (
          <ul className="space-y-3">
            {recentExperiments.map((exp: any) => (
              <li key={exp.id} className="flex items-center justify-between text-sm border-b border-gray-50 pb-2 last:border-b-0 last:pb-0">
                <div className="flex-1 min-w-0">
                  <div className="font-medium text-gray-800 truncate">{exp.name}</div>
                  <div className="text-xs text-gray-500 mt-0.5">
                    <span className="font-mono">{exp.project_name}</span>
                    {' · '}
                    <span>{exp.exp_type}</span>
                    {exp.iteration && <span> · 迭代 {exp.iteration}</span>}
                    {exp.created_at && (
                      <span> · {new Date(exp.created_at).toLocaleString('zh-CN')}</span>
                    )}
                  </div>
                </div>
                <div className="flex items-center gap-2 ml-3">
                  {exp.success === true && (
                    <Badge variant="status" value="success" />
                  )}
                  {exp.success === false && (
                    <Badge variant="status" value="failed" />
                  )}
                  <Badge variant="status" value={exp.status} />
                </div>
              </li>
            ))}
          </ul>
        ) : (
          <div className="text-center text-sm text-gray-400 py-12">暂无实验记录</div>
        )}
      </Card>
    </div>
  );
}
