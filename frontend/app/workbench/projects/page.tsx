'use client';

import { useState } from 'react';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { FolderKanban, Plus, Trash2, Archive, Play, Pause } from 'lucide-react';
import { getProjects, createProject } from '@/lib/api';
import Card from '@/components/ui/Card';
import Button from '@/components/ui/Button';
import Badge from '@/components/ui/Badge';

const STATUS_VARIANT: Record<string, 'gray' | 'blue' | 'green' | 'red'> = {
  active: 'green',
  paused: 'gray',
  archived: 'red',
  draft: 'gray',
};

const STATUS_LABEL: Record<string, string> = {
  active: '进行中',
  paused: '已暂停',
  archived: '已归档',
  draft: '草稿',
};

export default function ProjectsPage() {
  const queryClient = useQueryClient();
  const [showCreate, setShowCreate] = useState(false);
  const [newProject, setNewProject] = useState({
    name: '',
    description: '',
    cancer_type: '',
    stage: '',
    patient_pseudonym: '',
  });

  const { data: projects, isLoading, isError, refetch } = useQuery({
    queryKey: ['projects'],
    queryFn: getProjects,
  });

  const createMutation = useMutation({
    mutationFn: () => createProject(newProject),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['projects'] });
      setShowCreate(false);
      setNewProject({ name: '', description: '', cancer_type: '', stage: '', patient_pseudonym: '' });
    },
  });

  const projectList: any[] = Array.isArray(projects) ? projects : (projects as any)?.data || [];

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold flex items-center gap-2">
            <FolderKanban className="w-6 h-6" /> 项目管理
          </h1>
          <p className="text-sm text-gray-500 mt-1">研究项目全生命周期管理 — 创建/暂停/归档</p>
        </div>
        <Button onClick={() => setShowCreate(true)}>
          <Plus className="w-4 h-4" /> 新建项目
        </Button>
      </div>

      {isError ? (
        <div className="rounded-xl border border-red-200 bg-red-50 p-6 text-center">
          <p className="text-sm text-red-600 mb-3">数据加载失败</p>
          <button onClick={() => refetch()} className="text-xs text-primary-600 underline">重试</button>
        </div>
      ) : isLoading ? (
        <Card className="p-8 text-center text-gray-500">加载中...</Card>
      ) : projectList.length === 0 ? (
        <Card className="p-8 text-center text-gray-500">
          <FolderKanban className="w-12 h-12 mx-auto mb-4 text-gray-300" />
          <p>暂无项目</p>
          <p className="text-xs mt-2">点击右上角"新建项目"开始</p>
        </Card>
      ) : (
        <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
          {projectList.map((project: any) => (
            <Card key={project.id} className="p-5">
              <div className="flex items-start justify-between mb-3">
                <h3 className="font-semibold truncate">{project.name}</h3>
                <Badge variant={STATUS_VARIANT[project.status] || 'gray'}>
                  {STATUS_LABEL[project.status] || project.status}
                </Badge>
              </div>
              {project.description && (
                <p className="text-sm text-gray-500 mb-3 line-clamp-2">{project.description}</p>
              )}
              <div className="grid grid-cols-2 gap-2 text-xs text-gray-500 mb-3">
                {project.cancer_type && (
                  <div>
                    <span className="text-gray-400">疾病:</span> {project.cancer_type}
                  </div>
                )}
                {project.stage && (
                  <div>
                    <span className="text-gray-400">分期:</span> {project.stage}
                  </div>
                )}
              </div>
              <div className="flex gap-2 pt-3 border-t">
                <Button variant="secondary" size="sm">
                  <Play className="w-3 h-3" /> 进入
                </Button>
                {project.status === 'active' && (
                  <Button variant="secondary" size="sm">
                    <Pause className="w-3 h-3" /> 暂停
                  </Button>
                )}
                {project.status !== 'archived' && (
                  <Button variant="secondary" size="sm">
                    <Archive className="w-3 h-3" /> 归档
                  </Button>
                )}
              </div>
              <p className="text-xs text-gray-400 mt-2">
                创建: {project.created_at ? new Date(project.created_at).toLocaleDateString() : '-'}
              </p>
            </Card>
          ))}
        </div>
      )}

      {showCreate && (
        <div className="fixed inset-0 bg-black/50 flex items-center justify-center z-50" onClick={() => setShowCreate(false)}>
          <Card className="p-6 w-[480px]" onClick={(e: any) => e.stopPropagation()}>
            <h3 className="font-semibold mb-4">新建项目</h3>
            <div className="space-y-3">
              <div>
                <label className="block text-sm text-gray-600 mb-1">项目名称 *</label>
                <input
                  type="text"
                  value={newProject.name}
                  onChange={(e) => setNewProject({ ...newProject, name: e.target.value })}
                  className="w-full border rounded px-3 py-2"
                  placeholder="如：EGFR T790M 耐药机制研究"
                />
              </div>
              <div>
                <label className="block text-sm text-gray-600 mb-1">描述</label>
                <textarea
                  value={newProject.description}
                  onChange={(e) => setNewProject({ ...newProject, description: e.target.value })}
                  className="w-full border rounded px-3 py-2"
                  rows={2}
                />
              </div>
              <div className="grid grid-cols-2 gap-3">
                <div>
                  <label className="block text-sm text-gray-600 mb-1">疾病类型</label>
                  <input
                    type="text"
                    value={newProject.cancer_type}
                    onChange={(e) => setNewProject({ ...newProject, cancer_type: e.target.value })}
                    className="w-full border rounded px-3 py-2"
                    placeholder="如：非小细胞肺癌"
                  />
                </div>
                <div>
                  <label className="block text-sm text-gray-600 mb-1">分期</label>
                  <input
                    type="text"
                    value={newProject.stage}
                    onChange={(e) => setNewProject({ ...newProject, stage: e.target.value })}
                    className="w-full border rounded px-3 py-2"
                    placeholder="如：IIIB"
                  />
                </div>
              </div>
              <div>
                <label className="block text-sm text-gray-600 mb-1">患者标识（假名）</label>
                <input
                  type="text"
                  value={newProject.patient_pseudonym}
                  onChange={(e) => setNewProject({ ...newProject, patient_pseudonym: e.target.value })}
                  className="w-full border rounded px-3 py-2"
                  placeholder="HIPAA Safe Harbor 脱敏后的患者标识"
                />
              </div>
              <div className="flex gap-2 justify-end pt-2">
                <Button variant="secondary" onClick={() => setShowCreate(false)}>取消</Button>
                <Button
                  loading={createMutation.isPending}
                  onClick={() => createMutation.mutate()}
                  disabled={!newProject.name}
                >
                  创建
                </Button>
              </div>
            </div>
          </Card>
        </div>
      )}
    </div>
  );
}
