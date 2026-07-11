'use client';

import { useState, FormEvent } from 'react';
import { useRouter } from 'next/navigation';
import { Dna, AlertCircle } from 'lucide-react';
import { login } from '@/lib/auth';
import { useAppStore } from '@/lib/store';
import Button from '@/components/ui/Button';

export default function LoginPage() {
  const router = useRouter();
  const { setUser } = useAppStore();
  const [email, setEmail] = useState('sid@ai-drug.com');
  const [password, setPassword] = useState('demo123456');
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');

  const handleSubmit = async (e: FormEvent) => {
    e.preventDefault();
    setLoading(true);
    setError('');
    try {
      const user = await login(email, password);
      setUser({ role: user.role, name: user.name, email: user.email });
      router.push('/workbench');
    } catch (err: any) {
      setError(err.response?.data?.detail || '登录失败，请检查邮箱和密码');
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="min-h-screen flex items-center justify-center bg-gradient-to-br from-primary-50 via-white to-accent/10 px-4">
      <div className="max-w-md w-full">
        {/* 标题 */}
        <div className="text-center mb-8">
          <div className="inline-flex items-center justify-center w-16 h-16 rounded-2xl bg-primary-600 text-white mb-4">
            <Dna className="w-8 h-8" />
          </div>
          <h1 className="text-2xl font-bold text-gray-900">AI模式精准药物设计系统</h1>
          <p className="mt-2 text-sm text-gray-500">
            干湿闭环 · 多假设并行 · 老药新用 · CDISC 标准 · 分级分析
          </p>
        </div>

        {/* 登录卡片 */}
        <div className="bg-white rounded-xl shadow-card border border-gray-100 p-8">
          <form onSubmit={handleSubmit} className="space-y-4">
            <div>
              <label className="block text-sm font-medium text-gray-700 mb-1">邮箱</label>
              <input
                type="email"
                value={email}
                onChange={(e) => setEmail(e.target.value)}
                required
                className="w-full px-3 py-2 border border-gray-300 rounded-md focus:outline-none focus:ring-2 focus:ring-primary-500 focus:border-primary-500 text-sm"
                placeholder="your@email.com"
              />
            </div>
            <div>
              <label className="block text-sm font-medium text-gray-700 mb-1">密码</label>
              <input
                type="password"
                value={password}
                onChange={(e) => setPassword(e.target.value)}
                required
                className="w-full px-3 py-2 border border-gray-300 rounded-md focus:outline-none focus:ring-2 focus:ring-primary-500 focus:border-primary-500 text-sm"
                placeholder="••••••••"
              />
            </div>

            {error && (
              <div className="flex items-center gap-2 text-sm text-danger bg-red-50 px-3 py-2 rounded-md">
                <AlertCircle className="w-4 h-4 shrink-0" />
                <span>{error}</span>
              </div>
            )}

            <Button type="submit" loading={loading} className="w-full" size="lg">
              {loading ? '登录中...' : '登录'}
            </Button>
          </form>

          {/* 演示账号 */}
          <div className="mt-6 p-3 bg-yellow-50 border border-yellow-200 rounded-md text-xs text-yellow-800">
            <div className="font-semibold mb-1">演示账号</div>
            <div>邮箱：sid@ai-drug.com</div>
            <div>密码：demo123456</div>
            <div className="mt-1 text-yellow-700">5 个角色账号：founder/chief/researcher/doctor/engineer</div>
          </div>
        </div>

        <p className="mt-6 text-center text-xs text-gray-400">
          灵感来源于 GitLab 联合创始人 Sid Sijbrandij 的个性化癌症治疗经历
        </p>
      </div>
    </div>
  );
}
