'use client';

import { useEffect, useState } from 'react';
import { useRouter } from 'next/navigation';
import { Settings, Activity, ArrowLeft } from 'lucide-react';
import Link from 'next/link';
import { getCurrentUser, isLoggedIn } from '@/lib/auth';
import LLMConfigCard from '@/components/admin/LLMConfigCard';
import LLMMonitoringCard from '@/components/admin/LLMMonitoringCard';
import clsx from 'clsx';

export default function AdminLlmPage() {
  const router = useRouter();
  const [user, setUser] = useState<any>(null);
  const [activeTab, setActiveTab] = useState<'config' | 'monitor'>('config');

  useEffect(() => {
    const u = getCurrentUser();
    setUser(u);
    if (u && u.role !== 'founder' && u.role !== 'chief') {
      router.replace('/admin');
    }
  }, [router]);

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
            <Settings className="w-6 h-6" /> LLM 配置管理
          </h1>
          <p className="text-sm text-gray-500 mt-1">大模型配置 · 激活切换 · 连通性测试 · 性能监控</p>
        </div>
      </div>

      {/* Tab 切换 */}
      <div className="flex gap-2 border-b">
        <button
          onClick={() => setActiveTab('config')}
          className={clsx(
            'flex items-center gap-2 px-4 py-2 text-sm font-medium border-b-2 transition-colors',
            activeTab === 'config'
              ? 'border-primary-600 text-primary-600'
              : 'border-transparent text-gray-500 hover:text-gray-700'
          )}
        >
          <Settings className="w-4 h-4" /> 配置管理
        </button>
        <button
          onClick={() => setActiveTab('monitor')}
          className={clsx(
            'flex items-center gap-2 px-4 py-2 text-sm font-medium border-b-2 transition-colors',
            activeTab === 'monitor'
              ? 'border-primary-600 text-primary-600'
              : 'border-transparent text-gray-500 hover:text-gray-700'
          )}
        >
          <Activity className="w-4 h-4" /> 性能监控
        </button>
      </div>

      {activeTab === 'config' ? <LLMConfigCard /> : <LLMMonitoringCard />}
    </div>
  );
}
