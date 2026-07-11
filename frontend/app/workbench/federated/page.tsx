'use client';

import { useState } from 'react';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { Network, Play, Square, Plus, RefreshCw } from 'lucide-react';
import { getFederatedJobs, createFederatedJob, stopFederatedJob } from '@/lib/api';
import { useAppStore } from '@/lib/store';
import Card from '@/components/ui/Card';
import Button from '@/components/ui/Button';
import Badge from '@/components/ui/Badge';

const STATUS_VARIANT: Record<string, 'gray' | 'blue' | 'green' | 'red'> = {
  pending: 'gray',
  running: 'blue',
  completed: 'green',
  failed: 'red',
};

export default function FederatedPage() {
  const { currentProject } = useAppStore();
  const queryClient = useQueryClient();
  const [showCreate, setShowCreate] = useState(false);
  const [newJob, setNewJob] = useState({ min_clients: 3, rounds: 10 });

  const { data: jobs, isLoading } = useQuery({
    queryKey: ['federated-jobs'],
    queryFn: getFederatedJobs,
  });

  const createMutation = useMutation({
    mutationFn: () =>
      createFederatedJob({
        project_id: currentProject?.id || '',
        min_clients: newJob.min_clients,
        rounds: newJob.rounds,
      }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['federated-jobs'] });
      setShowCreate(false);
    },
  });

  const stopMutation = useMutation({
    mutationFn: (jobId: string) => stopFederatedJob(jobId),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ['federated-jobs'] }),
  });

  // 兼容多种响应结构：信封已由拦截器解包，jobs 可能是 {items, count}、裸数组或 {data:{items}}
  const jobList: any[] =
    (jobs as any)?.items ||
    (jobs as any)?.data?.items ||
    (Array.isArray(jobs) ? jobs : []) ||
    [];

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold flex items-center gap-2">
            <Network className="w-6 h-6" /> 联邦学习
          </h1>
          <p className="text-sm text-gray-500 mt-1">多中心协同训练 — FedAvg + MAD 拜占庭剔除</p>
        </div>
        <div className="flex gap-2">
          <Button variant="secondary" onClick={() => queryClient.invalidateQueries({ queryKey: ['federated-jobs'] })}>
            <RefreshCw className="w-4 h-4" /> 刷新
          </Button>
          <Button onClick={() => setShowCreate(true)}>
            <Plus className="w-4 h-4" /> 新建训练任务
          </Button>
        </div>
      </div>

      {isLoading ? (
        <Card className="p-8 text-center text-gray-500">加载中...</Card>
      ) : jobList.length === 0 ? (
        <Card className="p-8 text-center text-gray-500">
          <Network className="w-12 h-12 mx-auto mb-4 text-gray-300" />
          <p>暂无联邦学习任务</p>
          <p className="text-xs mt-2">点击右上角"新建训练任务"开始</p>
        </Card>
      ) : (
        <div className="grid gap-4">
          {jobList.map((job: any) => (
            <Card key={job.id} className="p-5">
              <div className="flex items-start justify-between">
                <div className="flex-1">
                  <div className="flex items-center gap-3 mb-2">
                    <h3 className="font-semibold">任务 #{job.id?.slice(0, 8)}</h3>
                    <Badge variant={STATUS_VARIANT[job.status] || 'gray'}>{job.status || 'unknown'}</Badge>
                  </div>
                  <div className="grid grid-cols-4 gap-4 text-sm">
                    <div>
                      <p className="text-gray-500">当前轮次</p>
                      <p className="font-medium">{job.current_round || 0} / {job.rounds || '-'}</p>
                    </div>
                    <div>
                      <p className="text-gray-500">参与客户端</p>
                      <p className="font-medium">{job.participated_clients || 0} / {job.min_clients || '-'}</p>
                    </div>
                    <div>
                      <p className="text-gray-500">创建时间</p>
                      <p className="font-medium text-xs">{job.created_at ? new Date(job.created_at).toLocaleString() : '-'}</p>
                    </div>
                    <div>
                      <p className="text-gray-500">项目</p>
                      <p className="font-medium text-xs">{job.project_id?.slice(0, 8) || '-'}</p>
                    </div>
                  </div>
                </div>
                {job.status === 'running' && (
                  <Button
                    variant="secondary"
                    size="sm"
                    loading={stopMutation.isPending}
                    onClick={() => stopMutation.mutate(job.id)}
                  >
                    <Square className="w-4 h-4" /> 停止
                  </Button>
                )}
              </div>
            </Card>
          ))}
        </div>
      )}

      {showCreate && (
        <div className="fixed inset-0 bg-black/50 flex items-center justify-center z-50" onClick={() => setShowCreate(false)}>
          <Card className="p-6 w-96" onClick={(e: any) => e.stopPropagation()}>
            <h3 className="font-semibold mb-4">新建联邦学习任务</h3>
            <div className="space-y-4">
              <div>
                <label className="block text-sm text-gray-600 mb-1">最小客户端数</label>
                <input
                  type="number"
                  value={newJob.min_clients}
                  onChange={(e) => setNewJob({ ...newJob, min_clients: Number(e.target.value) })}
                  className="w-full border rounded px-3 py-2"
                  min={1}
                />
              </div>
              <div>
                <label className="block text-sm text-gray-600 mb-1">训练轮次</label>
                <input
                  type="number"
                  value={newJob.rounds}
                  onChange={(e) => setNewJob({ ...newJob, rounds: Number(e.target.value) })}
                  className="w-full border rounded px-3 py-2"
                  min={1}
                />
              </div>
              <div className="flex gap-2 justify-end">
                <Button variant="secondary" onClick={() => setShowCreate(false)}>取消</Button>
                <Button loading={createMutation.isPending} onClick={() => createMutation.mutate()}>
                  <Play className="w-4 h-4" /> 启动
                </Button>
              </div>
            </div>
          </Card>
        </div>
      )}
    </div>
  );
}
