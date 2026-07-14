'use client';

import { useEffect, useState } from 'react';
import { useRouter } from 'next/navigation';
import { useQuery } from '@tanstack/react-query';
import { ScrollText, ArrowLeft, Shield } from 'lucide-react';
import Link from 'next/link';
import { getAuditLogs, getCurrentUser, isLoggedIn } from '@/lib/api';
import { getCurrentUser as getLocalUser, isLoggedIn as isloggedInLocal } from '@/lib/auth';
import Card from '@/components/ui/Card';
import Badge from '@/components/ui/Badge';

export default function AdminAuditPage() {
  const router = useRouter();
  const [user, setUser] = useState<any>(null);

  useEffect(() => {
    const u = getLocalUser();
    setUser(u);
    if (u && u.role !== 'founder' && u.role !== 'chief') {
      router.replace('/admin');
    }
  }, [router]);

  const { data: auditLogsResp, isLoading } = useQuery({
    queryKey: ['audit-logs'],
    queryFn: () => getAuditLogs(100),
    enabled: !!user && (user.role === 'founder' || user.role === 'chief'),
  });
  const auditLogs = (auditLogsResp as any)?.data?.logs || (auditLogsResp as any)?.logs || [];

  if (!user) {
    return <div className="text-center py-12 text-gray-400">加载中...</div>;
  }

  return (
    <div className="space-y-6">
      <div className="flex items-center gap-3">
        <Link href="/admin" prefetch={false} className="text-gray-500 hover:text-gray-700">
          <ArrowLeft className="w-5 h-5" />
        </Link>
        <div>
          <h1 className="text-2xl font-bold flex items-center gap-2">
            <ScrollText className="w-6 h-6" /> 审计日志
          </h1>
          <p className="text-sm text-gray-500 mt-1">不可篡改的操作记录 · 数据访问追踪</p>
        </div>
      </div>

      <Card title={`审计日志 (${auditLogs?.length || 0})`} action={<ScrollText className="w-4 h-4 text-gray-400" />}>
        {isLoading ? (
          <div className="text-center py-8 text-gray-400">加载中...</div>
        ) : auditLogs && auditLogs.length > 0 ? (
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b border-gray-200 text-gray-500">
                  <th className="text-left py-2 px-3">时间</th>
                  <th className="text-left py-2 px-3">用户</th>
                  <th className="text-left py-2 px-3">操作</th>
                  <th className="text-left py-2 px-3">资源</th>
                  <th className="text-left py-2 px-3">详情</th>
                </tr>
              </thead>
              <tbody>
                {auditLogs.map((log: any) => (
                  <tr key={log.id} className="border-b border-gray-100 hover:bg-gray-50">
                    <td className="py-2 px-3 text-xs text-gray-500">
                      {log.created_at ? new Date(log.created_at).toLocaleString('zh-CN') : '—'}
                    </td>
                    <td className="py-2 px-3 text-xs">
                      <div className="font-mono">{log.actor || '—'}</div>
                      {log.role && <div className="text-gray-400 text-[10px]">{log.role}</div>}
                    </td>
                    <td className="py-2 px-3">
                      <Badge variant="status" value={log.action || 'unknown'} />
                    </td>
                    <td className="py-2 px-3 text-xs font-mono">
                      {log.entity || '—'}{log.entity_id ? `:${String(log.entity_id).slice(0, 8)}` : ''}
                    </td>
                    <td className="py-2 px-3 text-xs text-gray-500">
                      {log.detail || '—'}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        ) : (
          <div className="text-center py-8 text-gray-400">
            <Shield className="w-12 h-12 mx-auto mb-2 opacity-50" />
            暂无审计日志
          </div>
        )}
      </Card>
    </div>
  );
}
