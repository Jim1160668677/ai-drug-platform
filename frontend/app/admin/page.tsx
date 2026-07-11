'use client';

import { useEffect, useState } from 'react';
import { useRouter } from 'next/navigation';
import Link from 'next/link';
import { Shield, Users, Settings, ScrollText, AlertTriangle, ArrowRight } from 'lucide-react';
import { getCurrentUser, isLoggedIn } from '@/lib/auth';
import Card from '@/components/ui/Card';
import Badge from '@/components/ui/Badge';

export default function AdminPage() {
  const router = useRouter();
  const [user, setUser] = useState<any>(null);

  useEffect(() => {
    if (!isLoggedIn()) {
      router.replace('/');
      return;
    }
    const u = getCurrentUser();
    setUser(u);
    if (u && u.role !== 'founder' && u.role !== 'chief') {
      // 非 founder/chief 显示 403
    }
  }, [router]);

  if (!user) {
    return <div className="text-center py-12 text-gray-400">加载中...</div>;
  }

  if (user.role !== 'founder' && user.role !== 'chief') {
    return (
      <div className="flex items-center justify-center min-h-[60vh]">
        <Card className="max-w-md">
          <div className="text-center py-6">
            <AlertTriangle className="w-12 h-12 mx-auto mb-3 text-yellow-500" />
            <h2 className="text-lg font-semibold">403 — 权限不足</h2>
            <p className="text-sm text-gray-500 mt-2">
              管理后台仅限创始人/首席研究员访问
            </p>
          </div>
        </Card>
      </div>
    );
  }

  const modules = [
    {
      href: '/admin/users',
      label: '用户管理',
      description: '用户列表 · 角色切换 · 启用/禁用',
      icon: Users,
      color: 'text-blue-500 bg-blue-50',
      restricted: user.role !== 'founder',
      restrictedText: '仅创始人可访问',
    },
    {
      href: '/admin/llm',
      label: 'LLM 配置',
      description: '大模型配置 · 激活切换 · 连通性测试',
      icon: Settings,
      color: 'text-purple-500 bg-purple-50',
      restricted: false,
    },
    {
      href: '/admin/audit',
      label: '审计日志',
      description: '不可篡改的操作记录 · 数据访问追踪',
      icon: ScrollText,
      color: 'text-green-500 bg-green-50',
      restricted: false,
    },
  ];

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-2xl font-bold flex items-center gap-2">
          <Shield className="w-6 h-6" /> 管理后台
        </h1>
        <p className="text-sm text-gray-500 mt-1">用户管理 · LLM 配置 · 审计日志</p>
      </div>

      <Card title="系统信息">
        <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
          <div className="bg-gray-50 p-3 rounded">
            <div className="text-xs text-gray-500">运行模式</div>
            <div className="text-sm font-semibold">Mock</div>
          </div>
          <div className="bg-gray-50 p-3 rounded">
            <div className="text-xs text-gray-500">API 版本</div>
            <div className="text-sm font-semibold">v1.0.0</div>
          </div>
          <div className="bg-gray-50 p-3 rounded">
            <div className="text-xs text-gray-500">当前用户</div>
            <div className="text-sm font-semibold">{user.email}</div>
          </div>
          <div className="bg-gray-50 p-3 rounded">
            <div className="text-xs text-gray-500">角色</div>
            <Badge variant="role" value={user.role} />
          </div>
        </div>
      </Card>

      <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
        {modules.map((mod) => {
          const Icon = mod.icon;
          return (
            <Link
              key={mod.href}
              href={mod.restricted ? '#' : mod.href}
              className={mod.restricted ? 'pointer-events-none' : ''}
            >
              <Card className={`p-6 h-full transition-shadow hover:shadow-md ${mod.restricted ? 'opacity-50' : ''}`}>
                <div className={`w-12 h-12 rounded-lg ${mod.color} flex items-center justify-center mb-4`}>
                  <Icon className="w-6 h-6" />
                </div>
                <h3 className="font-semibold mb-1">{mod.label}</h3>
                <p className="text-sm text-gray-500 mb-4">{mod.description}</p>
                {mod.restricted ? (
                  <span className="text-xs text-gray-400">{mod.restrictedText}</span>
                ) : (
                  <span className="text-xs text-primary-600 flex items-center gap-1">
                    进入 <ArrowRight className="w-3 h-3" />
                  </span>
                )}
              </Card>
            </Link>
          );
        })}
      </div>
    </div>
  );
}
