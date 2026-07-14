'use client';

import { useEffect, useState } from 'react';
import { useRouter } from 'next/navigation';
import { Users, ArrowLeft } from 'lucide-react';
import Link from 'next/link';
import { getCurrentUser, isLoggedIn } from '@/lib/auth';
import UserListCard from '@/components/admin/UserListCard';

export default function AdminUsersPage() {
  const router = useRouter();
  const [user, setUser] = useState<any>(null);

  useEffect(() => {
    const u = getCurrentUser();
    setUser(u);
    if (u && u.role !== 'founder') {
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
            <Users className="w-6 h-6" /> 用户管理
          </h1>
          <p className="text-sm text-gray-500 mt-1">用户列表 · 角色切换 · 启用/禁用</p>
        </div>
      </div>
      <UserListCard />
    </div>
  );
}
