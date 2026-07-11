'use client';

import { useQuery } from '@tanstack/react-query';
import Link from 'next/link';
import {
  Database,
  Target,
  FlaskConical,
  GitBranch,
  Upload,
  Search,
  MessageSquare,
  FileText,
  TrendingUp,
} from 'lucide-react';
import { getProjects, getDatasets, getTargets, getExperiments } from '@/lib/api';
import { useAppStore } from '@/lib/store';
import Card from '@/components/ui/Card';
import Badge from '@/components/ui/Badge';
import Button from '@/components/ui/Button';

export default function WorkbenchHome() {
  const { currentProject } = useAppStore();
  const projectId = currentProject?.id;

  const { data: projects } = useQuery({ queryKey: ['projects'], queryFn: getProjects });
  const { data: datasets } = useQuery({
    queryKey: ['datasets', projectId],
    queryFn: () => getDatasets(projectId),
    enabled: !!projectId,
  });
  const { data: targets } = useQuery({
    queryKey: ['targets', projectId],
    queryFn: () => getTargets(projectId),
    enabled: !!projectId,
  });
  const { data: experiments } = useQuery({
    queryKey: ['experiments', projectId],
    queryFn: () => getExperiments(projectId),
    enabled: !!projectId,
  });

  const stats = [
    { label: '项目数', value: projects?.length || 0, icon: GitBranch, color: 'text-primary-600 bg-primary-50' },
    { label: '数据集', value: datasets?.length || 0, icon: Database, color: 'text-accent bg-emerald-50' },
    { label: '靶点', value: targets?.length || 0, icon: Target, color: 'text-purple-600 bg-purple-50' },
    { label: '实验', value: experiments?.length || 0, icon: FlaskConical, color: 'text-amber-600 bg-amber-50' },
  ];

  const recentExperiments = (experiments || []).slice(0, 5);

  return (
    <div className="space-y-6">
      {/* 页面标题 */}
      <div>
        <h1 className="text-2xl font-bold text-gray-900">工作台</h1>
        <p className="text-sm text-gray-500 mt-1">
          {currentProject
            ? `当前项目：${currentProject.name} · ${currentProject.cancer_type || ''} · 分期 ${currentProject.stage || '未知'}`
            : '请选择项目'}
        </p>
      </div>

      {/* 统计卡片 */}
      <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-4">
        {stats.map((s) => {
          const Icon = s.icon;
          return (
            <Card key={s.label}>
              <div className="flex items-center justify-between">
                <div>
                  <div className="text-3xl font-bold text-gray-900">{s.value}</div>
                  <div className="text-sm text-gray-500 mt-1">{s.label}</div>
                </div>
                <div className={`w-12 h-12 rounded-lg flex items-center justify-center ${s.color}`}>
                  <Icon className="w-6 h-6" />
                </div>
              </div>
            </Card>
          );
        })}
      </div>

      {/* 快速操作 */}
      <Card title="快速操作">
        <div className="grid grid-cols-2 sm:grid-cols-4 gap-3">
          <Link href="/workbench/data" prefetch={false}>
            <Button variant="secondary" className="w-full">
              <Upload className="w-4 h-4" /> 上传数据
            </Button>
          </Link>
          <Link href="/workbench/targets" prefetch={false}>
            <Button variant="secondary" className="w-full">
              <Search className="w-4 h-4" /> 发现靶点
            </Button>
          </Link>
          <Link href="/workbench/chat" prefetch={false}>
            <Button variant="secondary" className="w-full">
              <MessageSquare className="w-4 h-4" /> AI 提问
            </Button>
          </Link>
          <Link href="/reports" prefetch={false}>
            <Button variant="secondary" className="w-full">
              <FileText className="w-4 h-4" /> 导出报告
            </Button>
          </Link>
        </div>
      </Card>

      {/* 当前项目信息 + 最近活动 */}
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
        <Card title="当前项目">
          {currentProject ? (
            <div className="space-y-3">
              <div>
                <div className="text-sm text-gray-500">项目名称</div>
                <div className="text-base font-medium">{currentProject.name}</div>
              </div>
              <div className="grid grid-cols-2 gap-4">
                <div>
                  <div className="text-sm text-gray-500">癌种</div>
                  <div className="text-base">{currentProject.cancer_type || '—'}</div>
                </div>
                <div>
                  <div className="text-sm text-gray-500">分期</div>
                  <div className="text-base">{currentProject.stage || '—'}</div>
                </div>
              </div>
              <div>
                <div className="text-sm text-gray-500">状态</div>
                <Badge variant="status" value={currentProject.status || 'active'} />
              </div>
            </div>
          ) : (
            <div className="text-sm text-gray-400">未选择项目</div>
          )}
        </Card>

        <Card title="最近活动" action={<TrendingUp className="w-4 h-4 text-gray-400" />}>
          {recentExperiments.length > 0 ? (
            <ul className="space-y-3">
              {recentExperiments.map((exp: any) => (
                <li key={exp.id} className="flex items-center justify-between text-sm">
                  <div>
                    <div className="font-medium text-gray-800">{exp.name}</div>
                    <div className="text-xs text-gray-500">
                      {exp.exp_type} · 迭代 {exp.iteration || 1}
                    </div>
                  </div>
                  <Badge variant="status" value={exp.status} />
                </li>
              ))}
            </ul>
          ) : (
            <div className="text-sm text-gray-400">暂无实验记录</div>
          )}
        </Card>
      </div>
    </div>
  );
}
