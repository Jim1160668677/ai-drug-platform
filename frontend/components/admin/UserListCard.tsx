'use client';

import { useState } from 'react';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { Users, UserCheck, UserX, ChevronDown } from 'lucide-react';
import { getUsers, updateUserRole, updateUserStatus } from '@/lib/api';
import { getCurrentUser } from '@/lib/auth';
import Card from '@/components/ui/Card';
import Badge from '@/components/ui/Badge';

const ROLE_OPTIONS = [
  { value: 'researcher', label: '研究员' },
  { value: 'doctor', label: '医生' },
  { value: 'data_engineer', label: '数据工程师' },
  { value: 'chief_researcher', label: '首席研究员' },
];

const ROLE_LABELS: Record<string, string> = {
  founder: '创始人',
  chief_researcher: '首席研究员',
  researcher: '研究员',
  doctor: '医生',
  data_engineer: '数据工程师',
};

export default function UserListCard() {
  const queryClient = useQueryClient();
  const currentUser = getCurrentUser();
  const [roleFilter, setRoleFilter] = useState<string>('');
  const [statusFilter, setStatusFilter] = useState<string>('');

  const { data, isLoading } = useQuery({
    queryKey: ['users', roleFilter, statusFilter],
    queryFn: () => {
      const params: any = { limit: 200 };
      if (roleFilter) params.role = roleFilter;
      if (statusFilter === 'active') params.is_active = true;
      if (statusFilter === 'inactive') params.is_active = false;
      return getUsers(params);
    },
  });

  const users = (data as any)?.items || [];
  const total = (data as any)?.total || 0;

  const roleMutation = useMutation({
    mutationFn: ({ userId, role }: { userId: string; role: string }) =>
      updateUserRole(userId, role),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ['users'] }),
  });

  const statusMutation = useMutation({
    mutationFn: ({ userId, isActive }: { userId: string; isActive: boolean }) =>
      updateUserStatus(userId, isActive),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ['users'] }),
  });

  const handleRoleChange = (userId: string, currentRole: string) => {
    const select = document.createElement('select');
    select.className = 'sr-only';
    ROLE_OPTIONS.forEach((opt) => {
      const option = document.createElement('option');
      option.value = opt.value;
      option.text = opt.label;
      if (opt.value === currentRole) option.selected = true;
      select.appendChild(option);
    });
    select.onchange = () => {
      if (select.value && select.value !== currentRole) {
        roleMutation.mutate({ userId, role: select.value });
      }
    };
    select.click();
  };

  return (
    <Card
      title={`用户列表 (${total})`}
      action={
        <div className="flex gap-2">
          <select
            value={roleFilter}
            onChange={(e) => setRoleFilter(e.target.value)}
            className="text-xs border border-gray-200 rounded px-2 py-1 bg-white"
          >
            <option value="">全部角色</option>
            {ROLE_OPTIONS.map((r) => (
              <option key={r.value} value={r.value}>{r.label}</option>
            ))}
          </select>
          <select
            value={statusFilter}
            onChange={(e) => setStatusFilter(e.target.value)}
            className="text-xs border border-gray-200 rounded px-2 py-1 bg-white"
          >
            <option value="">全部状态</option>
            <option value="active">已启用</option>
            <option value="inactive">已禁用</option>
          </select>
        </div>
      }
    >
      {isLoading ? (
        <div className="text-center py-8 text-gray-400">加载中...</div>
      ) : users.length > 0 ? (
        <div className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b border-gray-200 text-gray-500">
                <th className="text-left py-2 px-3">邮箱</th>
                <th className="text-left py-2 px-3">姓名</th>
                <th className="text-left py-2 px-3">角色</th>
                <th className="text-left py-2 px-3">组织</th>
                <th className="text-left py-2 px-3">状态</th>
                <th className="text-left py-2 px-3">创建时间</th>
                <th className="text-left py-2 px-3">操作</th>
              </tr>
            </thead>
            <tbody>
              {users.map((u: any) => {
                const isSelf = currentUser?.email === u.email;
                const isFounder = u.role === 'founder';
                return (
                  <tr key={u.id} className="border-b border-gray-100 hover:bg-gray-50">
                    <td className="py-2 px-3 font-mono text-xs">{u.email}</td>
                    <td className="py-2 px-3">{u.name}</td>
                    <td className="py-2 px-3">
                      <Badge variant="role" value={u.role === 'chief_researcher' ? 'chief' : u.role === 'data_engineer' ? 'engineer' : u.role} />
                    </td>
                    <td className="py-2 px-3 text-xs text-gray-500">{u.organization || '—'}</td>
                    <td className="py-2 px-3">
                      {u.is_active ? (
                        <span className="inline-flex items-center gap-1 text-xs text-green-700">
                          <UserCheck className="w-3 h-3" /> 启用
                        </span>
                      ) : (
                        <span className="inline-flex items-center gap-1 text-xs text-red-600">
                          <UserX className="w-3 h-3" /> 禁用
                        </span>
                      )}
                    </td>
                    <td className="py-2 px-3 text-xs text-gray-500">
                      {u.created_at ? new Date(u.created_at).toLocaleDateString('zh-CN') : '—'}
                    </td>
                    <td className="py-2 px-3">
                      <div className="flex gap-1">
                        {!isSelf && !isFounder && (
                          <>
                            <select
                              value={u.role}
                              onChange={(e) => {
                                if (e.target.value !== u.role) {
                                  roleMutation.mutate({ userId: u.id, role: e.target.value });
                                }
                              }}
                              className="text-xs border border-gray-200 rounded px-1 py-0.5 bg-white"
                            >
                              {ROLE_OPTIONS.map((r) => (
                                <option key={r.value} value={r.value}>{r.label}</option>
                              ))}
                            </select>
                            <button
                              onClick={() => statusMutation.mutate({ userId: u.id, isActive: !u.is_active })}
                              className="text-xs px-2 py-0.5 rounded border border-gray-200 hover:bg-gray-100"
                              disabled={statusMutation.isPending}
                            >
                              {u.is_active ? '禁用' : '启用'}
                            </button>
                          </>
                        )}
                        {(isSelf || isFounder) && (
                          <span className="text-xs text-gray-400">—</span>
                        )}
                      </div>
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      ) : (
        <div className="text-center py-8 text-gray-400">
          <Users className="w-12 h-12 mx-auto mb-2 opacity-50" />
          暂无用户数据
        </div>
      )}
    </Card>
  );
}
