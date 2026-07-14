'use client';

import { useEffect, useState } from 'react';
import { useQuery } from '@tanstack/react-query';
import { LogOut, User, ChevronDown } from 'lucide-react';
import clsx from 'clsx';
import { getProjects } from '@/lib/api';
import { logout, getCurrentUser } from '@/lib/auth';
import { useAppStore } from '@/lib/store';
import { useMounted } from '@/lib/hooks/useMounted';
import Badge from '@/components/ui/Badge';

export default function Header() {
  const [open, setOpen] = useState(false);
  const { currentProject, setProject, user, setUser } = useAppStore();
  const mounted = useMounted();

  const { data: projects } = useQuery({
    queryKey: ['projects'],
    queryFn: getProjects,
  });

  useEffect(() => {
    if (!user) {
      const u = getCurrentUser();
      if (u) setUser({ role: u.role, name: u.name, email: u.email });
    }
  }, [user, setUser]);

  useEffect(() => {
    if (!currentProject && projects && projects.length > 0) {
      setProject(projects[0]);
    }
  }, [projects, currentProject, setProject]);

  const handleLogout = () => {
    logout();
  };

  return (
    <header className="bg-white border-b border-gray-200">
      {/* Mock 模式提示条 */}
      <div className="bg-yellow-50 border-b border-yellow-200 px-4 py-1.5 text-xs text-yellow-800 text-center">
        当前为 Mock 模式 — 配置 API key 后可切换真实模式
      </div>

      <div className="flex items-center justify-between h-14 px-6">
        {/* 左：项目选择器 */}
        <div className="flex items-center gap-3">
          <span className="text-sm text-gray-500">当前项目：</span>
          <select
            value={currentProject?.id || ''}
            onChange={(e) => {
              const p = projects?.find((x: any) => x.id === e.target.value);
              if (p) setProject(p);
            }}
            className="text-sm border border-gray-300 rounded px-2 py-1 focus:outline-none focus:ring-2 focus:ring-primary-500"
          >
            {projects?.map((p: any) => (
              <option key={p.id} value={p.id}>
                {p.name}
              </option>
            ))}
          </select>
          {currentProject && (
            <div className="flex items-center gap-2 text-xs text-gray-500">
              <span>{currentProject.cancer_type}</span>
              <span>·</span>
              <span>分期 {currentProject.stage}</span>
            </div>
          )}
        </div>

        {/* 右：用户菜单 */}
        <div className="relative">
          <button
            onClick={() => setOpen(!open)}
            className="flex items-center gap-2 px-3 py-1.5 rounded hover:bg-gray-100"
          >
            <div className="w-8 h-8 rounded-full bg-primary-600 text-white flex items-center justify-center">
              <User className="w-4 h-4" />
            </div>
            <div className="text-left">
              <div className="text-sm font-medium">{mounted ? (user?.name || '用户') : '用户'}</div>
              <div className="text-xs text-gray-500">{mounted ? user?.email : ''}</div>
            </div>
            {mounted && user?.role && <Badge variant="role" value={user.role} />}
            <ChevronDown className="w-4 h-4 text-gray-400" />
          </button>

          {open && (
            <>
              <div className="fixed inset-0 z-10" onClick={() => setOpen(false)} />
              <div className="absolute right-0 mt-2 w-48 bg-white rounded-md shadow-lg border border-gray-200 z-20">
                <button
                  onClick={handleLogout}
                  className="w-full flex items-center gap-2 px-4 py-2 text-sm text-danger hover:bg-red-50"
                >
                  <LogOut className="w-4 h-4" />
                  退出登录
                </button>
              </div>
            </>
          )}
        </div>
      </div>
    </header>
  );
}
