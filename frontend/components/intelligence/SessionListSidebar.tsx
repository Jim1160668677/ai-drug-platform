'use client';

/**
 * SessionListSidebar — 统一智能会话列表侧边栏（组件 1/18）
 *
 * 功能：
 * - 列出当前用户的会话（支持 project_id 过滤）
 * - 新建会话（弹窗填 title / primary_mode）
 * - 归档/删除会话（下拉操作）
 *
 * 端点：GET/POST/PATCH /intelligence/sessions
 */
import { useState } from 'react';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { Plus, Archive, Trash2, MessageSquare, Inbox } from 'lucide-react';
import clsx from 'clsx';
import Button from '@/components/ui/Button';
import Badge from '@/components/ui/Badge';
import EmptyState from '@/components/ui/EmptyState';
import { SkeletonList } from '@/components/ui/Skeleton';
import { toast } from '@/lib/notification';
import { useAppStore } from '@/lib/store';
import {
  createSession,
  listSessions,
  archiveSession,
} from '@/lib/api';
import type { SessionResponse, PrimaryMode } from '@/types/intelligence';

interface SessionListSidebarProps {
  selectedSessionId?: string;
  onSelect?: (sessionId: string) => void;
  refreshKey?: number;
}

const MODE_LABELS: Record<string, string> = {
  chat: '问答',
  reasoning: '推理',
  agent: 'Agent',
  hybrid: '混合',
  auto: '自动',
};

export default function SessionListSidebar({
  selectedSessionId,
  onSelect,
  refreshKey = 0,
}: SessionListSidebarProps) {
  const queryClient = useQueryClient();
  const currentProject = useAppStore((s) => s.currentProject);
  const [showCreate, setShowCreate] = useState(false);
  const [newTitle, setNewTitle] = useState('');
  const [newMode, setNewMode] = useState<PrimaryMode>('auto');

  // 查询会话列表
  const { data, isLoading } = useQuery({
    queryKey: ['intelligence-sessions', currentProject?.id, refreshKey],
    queryFn: () =>
      listSessions({
        project_id: currentProject?.id,
        limit: 50,
      }),
    refetchInterval: false,
  });

  const sessions: SessionResponse[] = data?.items ?? [];

  // 新建会话
  const createMutation = useMutation({
    mutationFn: () =>
      createSession({
        title: newTitle.trim() || '新会话',
        project_id: currentProject?.id,
        primary_mode: newMode,
      }),
    onSuccess: (session) => {
      queryClient.invalidateQueries({ queryKey: ['intelligence-sessions'] });
      setShowCreate(false);
      setNewTitle('');
      setNewMode('auto');
      onSelect?.(session.id);
      toast.success('会话已创建');
    },
    onError: () => toast.error('创建会话失败'),
  });

  // 归档/删除
  const archiveMutation = useMutation({
    mutationFn: ({ id, status }: { id: string; status: 'archived' | 'deleted' }) =>
      archiveSession(id, status),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['intelligence-sessions'] });
      toast.success('操作成功');
    },
    onError: () => toast.error('操作失败'),
  });

  return (
    <div className="flex h-full flex-col bg-white border-r border-gray-200">
      {/* 头部：标题 + 新建按钮 */}
      <div className="flex items-center justify-between px-4 py-3 border-b border-gray-100">
        <h2 className="text-sm font-semibold text-gray-800 flex items-center gap-1.5">
          <MessageSquare className="w-4 h-4 text-primary-600" />
          统一智能
        </h2>
        <Button size="sm" variant="ghost" onClick={() => setShowCreate((v) => !v)}>
          <Plus className="w-4 h-4" />
          新建
        </Button>
      </div>

      {/* 新建会话表单 */}
      {showCreate && (
        <div className="px-4 py-3 border-b border-gray-100 bg-gray-50 space-y-2">
          <input
            type="text"
            value={newTitle}
            onChange={(e) => setNewTitle(e.target.value)}
            placeholder="会话标题（可选）"
            className="w-full px-3 py-1.5 text-sm border border-gray-300 rounded-md focus:outline-none focus:ring-1 focus:ring-primary-500"
            maxLength={200}
          />
          <select
            value={newMode}
            onChange={(e) => setNewMode(e.target.value as PrimaryMode)}
            className="w-full px-3 py-1.5 text-sm border border-gray-300 rounded-md focus:outline-none focus:ring-1 focus:ring-primary-500"
          >
            <option value="auto">自动路由</option>
            <option value="chat">问答模式</option>
            <option value="reasoning">推理模式</option>
            <option value="agent">Agent 模式</option>
            <option value="hybrid">混合模式</option>
          </select>
          <div className="flex gap-2">
            <Button
              size="sm"
              loading={createMutation.isPending}
              onClick={() => createMutation.mutate()}
              className="flex-1"
            >
              创建
            </Button>
            <Button size="sm" variant="secondary" onClick={() => setShowCreate(false)}>
              取消
            </Button>
          </div>
        </div>
      )}

      {/* 会话列表 */}
      <div className="flex-1 overflow-y-auto">
        {isLoading ? (
          <div className="p-4">
            <SkeletonList count={4} />
          </div>
        ) : sessions.length === 0 ? (
          <div className="p-4">
            <EmptyState
              icon={Inbox}
              title="暂无会话"
              description="点击「新建」开始对话"
            />
          </div>
        ) : (
          <ul className="py-1">
            {sessions.map((session) => (
              <li key={session.id}>
                <div
                  className={clsx(
                    'group flex items-start gap-2 px-4 py-2.5 cursor-pointer hover:bg-gray-50 transition-colors',
                    selectedSessionId === session.id && 'bg-primary-50 border-l-2 border-primary-600',
                  )}
                  onClick={() => onSelect?.(session.id)}
                >
                  <div className="flex-1 min-w-0">
                    <p className="text-sm font-medium text-gray-800 truncate">
                      {session.title}
                    </p>
                    <div className="flex items-center gap-2 mt-0.5">
                      <Badge variant="blue" className="text-xs">
                        {MODE_LABELS[session.primary_mode] ?? session.primary_mode}
                      </Badge>
                      <span className="text-xs text-gray-400">
                        {session.message_count} 条消息
                      </span>
                    </div>
                  </div>
                  {/* 操作按钮 */}
                  <div className="flex flex-col gap-1 opacity-0 group-hover:opacity-100 transition-opacity">
                    <button
                      title="归档"
                      className="p-1 text-gray-400 hover:text-amber-600"
                      onClick={(e) => {
                        e.stopPropagation();
                        archiveMutation.mutate({ id: session.id, status: 'archived' });
                      }}
                    >
                      <Archive className="w-3.5 h-3.5" />
                    </button>
                    <button
                      title="删除"
                      className="p-1 text-gray-400 hover:text-red-600"
                      onClick={(e) => {
                        e.stopPropagation();
                        if (confirm('确认删除此会话？')) {
                          archiveMutation.mutate({ id: session.id, status: 'deleted' });
                          if (selectedSessionId === session.id) onSelect?.('');
                        }
                      }}
                    >
                      <Trash2 className="w-3.5 h-3.5" />
                    </button>
                  </div>
                </div>
              </li>
            ))}
          </ul>
        )}
      </div>
    </div>
  );
}
