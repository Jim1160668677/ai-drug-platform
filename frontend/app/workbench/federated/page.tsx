'use client';

import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { Network, Play, Square, RefreshCw, CheckCircle, Clock, XCircle, Loader2, Info } from 'lucide-react';
import { getFederatedJobs, createFederatedJob, stopFederatedJob } from '@/lib/api';
import { useAppStore } from '@/lib/store';
import { toast } from '@/lib/notification';
import Card from '@/components/ui/Card';
import Button from '@/components/ui/Button';
import ProgressBar from '@/components/ui/ProgressBar';

const STATUS_META: Record<string, { label: string; color: string; icon: any }> = {
  pending: { label: '待启动', color: 'text-gray-600 bg-gray-100', icon: Clock },
  running: { label: '训练中', color: 'text-blue-600 bg-blue-100', icon: Loader2 },
  completed: { label: '已完成', color: 'text-green-600 bg-green-100', icon: CheckCircle },
  stopped: { label: '已停止', color: 'text-yellow-600 bg-yellow-100', icon: Square },
  failed: { label: '失败', color: 'text-red-600 bg-red-100', icon: XCircle },
};

export default function FederatedPage() {
  const { currentProject } = useAppStore();
  const queryClient = useQueryClient();

  const { data: jobs, isLoading, isError, refetch } = useQuery({
    queryKey: ['federated-jobs'],
    queryFn: () => getFederatedJobs(),
  });

  const startMutation = useMutation({
    mutationFn: () =>
      createFederatedJob({
        project_id: currentProject?.id || '',
        min_clients: 3,
        num_rounds: 10,
      }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['federated-jobs'] });
      toast.success('训练已启动', '联邦学习任务已创建，使用默认配置（3 客户端 · 10 轮）');
    },
    onError: (err: any) => {
      toast.error('启动失败', err?.response?.data?.error?.message || '请稍后重试');
    },
  });

  const stopMutation = useMutation({
    mutationFn: (jobId: string) => stopFederatedJob(jobId),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['federated-jobs'] });
      toast.success('已停止', '训练任务已停止');
    },
  });

  const jobList: any[] =
    (jobs as any)?.items ||
    (jobs as any)?.data?.items ||
    (Array.isArray(jobs) ? jobs : []) ||
    [];

  const runningCount = jobList.filter((j) => j.status === 'running').length;
  const completedCount = jobList.filter((j) => j.status === 'completed').length;

  return (
    <div className="space-y-6">
      {/* 标题区 */}
      <div>
        <h1 className="text-2xl font-bold flex items-center gap-2">
          <Network className="w-6 h-6" /> 联邦学习
        </h1>
        <p className="text-sm text-gray-500 mt-1">
          多中心协同训练 — 在不共享原始数据的前提下联合训练模型
        </p>
      </div>

      {/* 说明卡片 */}
      <Card className="bg-gradient-to-r from-indigo-50 to-blue-50 border-blue-100">
        <div className="flex items-start gap-3">
          <Info className="w-5 h-5 text-blue-600 mt-0.5 flex-shrink-0" />
          <div className="text-sm text-gray-700 space-y-1">
            <p className="font-medium text-blue-900">什么是联邦学习？</p>
            <p>
              联邦学习让多家医院/机构在不泄露患者原始数据的前提下，共同训练一个更强大的 AI 模型。
              每个参与方在本地训练，只上传模型参数（不包含原始数据），由中心服务器聚合后分发回各方。
            </p>
            <p className="text-xs text-gray-500 mt-2">
              采用 FedAvg 聚合算法 + MAD 拜占庭剔除，自动过滤恶意客户端。点击下方按钮即可一键启动，使用推荐配置。
            </p>
          </div>
        </div>
      </Card>

      {/* 一键启动 + 统计 */}
      <div className="flex items-center justify-between flex-wrap gap-4">
        <Button
          size="lg"
          loading={startMutation.isPending}
          onClick={() => startMutation.mutate()}
          disabled={!currentProject}
        >
          <Play className="w-5 h-5" /> 一键启动联邦训练
        </Button>
        {!currentProject && (
          <span className="text-xs text-gray-400">请先选择项目</span>
        )}
        <div className="flex items-center gap-4 text-sm">
          <div className="flex items-center gap-1.5">
            <span className="w-2 h-2 rounded-full bg-blue-500"></span>
            <span className="text-gray-600">训练中：<span className="font-semibold">{runningCount}</span></span>
          </div>
          <div className="flex items-center gap-1.5">
            <span className="w-2 h-2 rounded-full bg-green-500"></span>
            <span className="text-gray-600">已完成：<span className="font-semibold">{completedCount}</span></span>
          </div>
          <Button variant="ghost" size="sm" onClick={() => queryClient.invalidateQueries({ queryKey: ['federated-jobs'] })}>
            <RefreshCw className="w-4 h-4" /> 刷新
          </Button>
        </div>
      </div>

      {/* 任务列表 */}
      {isError ? (
        <div className="rounded-xl border border-red-200 bg-red-50 p-6 text-center">
          <p className="text-sm text-red-600 mb-3">数据加载失败</p>
          <button onClick={() => refetch()} className="text-xs text-primary-600 underline">重试</button>
        </div>
      ) : isLoading ? (
        <Card className="p-8 text-center text-gray-500">加载中...</Card>
      ) : jobList.length === 0 ? (
        <Card className="p-12 text-center text-gray-400">
          <Network className="w-12 h-12 mx-auto mb-3 text-gray-300" />
          <p className="text-sm">暂无联邦学习任务</p>
          <p className="text-xs mt-1">点击上方「一键启动联邦训练」开始</p>
        </Card>
      ) : (
        <div className="space-y-3">
          {jobList.map((job: any, index: number) => {
            const jobId = job.job_id || job.id;
            const status = job.status || 'pending';
            const meta = STATUS_META[status] || STATUS_META.pending;
            const StatusIcon = meta.icon;
            const currentRound = job.current_round || 0;
            const totalRounds = job.num_rounds || job.rounds || 10;
            const progress = totalRounds > 0 ? (currentRound / totalRounds) * 100 : 0;
            const clientCount = Array.isArray(job.registered_clients)
              ? job.registered_clients.length
              : job.participated_clients || 0;
            const minClients = job.min_clients || 3;

            return (
              <Card key={jobId || `job-${index}`} className="p-5">
                {/* 顶部：状态 + 操作 */}
                <div className="flex items-center justify-between mb-4">
                  <div className="flex items-center gap-3">
                    <span className={`inline-flex items-center gap-1.5 px-2.5 py-1 rounded-full text-xs font-medium ${meta.color}`}>
                      <StatusIcon className={`w-3.5 h-3.5 ${status === 'running' ? 'animate-spin' : ''}`} />
                      {meta.label}
                    </span>
                    <span className="text-sm font-medium text-gray-700">
                      任务 #{jobId?.slice(-8) || '—'}
                    </span>
                  </div>
                  {status === 'running' && (
                    <Button
                      variant="secondary"
                      size="sm"
                      loading={stopMutation.isPending}
                      onClick={() => stopMutation.mutate(jobId)}
                    >
                      <Square className="w-3.5 h-3.5" /> 停止
                    </Button>
                  )}
                </div>

                {/* 进度条 */}
                <div className="mb-3">
                  <ProgressBar
                    percent={progress}
                    status={status}
                    message={`第 ${currentRound} / ${totalRounds} 轮训练`}
                  />
                </div>

                {/* 底部：关键信息 */}
                <div className="grid grid-cols-3 gap-3 text-sm">
                  <div>
                    <p className="text-xs text-gray-400">参与客户端</p>
                    <p className="font-medium text-gray-700">{clientCount} / {minClients}</p>
                  </div>
                  <div>
                    <p className="text-xs text-gray-400">训练框架</p>
                    <p className="font-medium text-gray-700">
                      {job.framework === 'flower' ? 'Flower' : '内存模拟'}
                    </p>
                  </div>
                  <div>
                    <p className="text-xs text-gray-400">创建时间</p>
                    <p className="font-medium text-gray-700 text-xs">
                      {job.created_at ? new Date(job.created_at).toLocaleString('zh-CN', {
                        month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit'
                      }) : '—'}
                    </p>
                  </div>
                </div>
              </Card>
            );
          })}
        </div>
      )}
    </div>
  );
}
