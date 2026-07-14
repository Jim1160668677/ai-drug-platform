'use client';

import Link from 'next/link';
import { usePathname } from 'next/navigation';
import {
  LayoutDashboard,
  Database,
  Target,
  Atom,
  Pill,
  GitBranch,
  FlaskConical,
  MessageSquare,
  FileText,
  Shield,
  ChevronLeft,
  Dna,
  Globe,
  Network,
  Lock,
  Activity,
  FolderKanban,
  Share2,
  ShieldCheck,
} from 'lucide-react';
import clsx from 'clsx';
import { useAppStore } from '@/lib/store';

interface NavItem {
  href: string;
  label: string;
  icon: React.ComponentType<{ className?: string }>;
  roles?: string[];
}

const NAV_ITEMS: NavItem[] = [
  { href: '/dashboard', label: '全局看板', icon: Globe },
  { href: '/workbench', label: '工作台', icon: LayoutDashboard },
  { href: '/workbench/projects', label: '项目管理', icon: FolderKanban },
  { href: '/workbench/data', label: '数据管理', icon: Database },
  { href: '/workbench/targets', label: '靶点发现', icon: Target },
  { href: '/workbench/molecules', label: '分子库', icon: Atom },
  {
    href: '/workbench/treatments',
    label: '治疗方案',
    icon: Pill,
    roles: ['founder', 'chief', 'doctor'],
  },
  { href: '/workbench/hypotheses', label: '多假设并行', icon: GitBranch },
  { href: '/workbench/experiments', label: '干湿闭环', icon: FlaskConical },
  { href: '/workbench/lineage', label: '数据血缘', icon: Share2 },
  { href: '/workbench/chat', label: 'AI 问答', icon: MessageSquare },
  { href: '/workbench/federated', label: '联邦学习', icon: Network, roles: ['founder', 'chief', 'engineer'] },
  { href: '/workbench/privacy', label: '隐私计算', icon: Lock, roles: ['founder', 'chief', 'engineer'] },
  { href: '/workbench/efficacy', label: '疗效监测', icon: Activity, roles: ['founder', 'chief', 'doctor'] },
  { href: '/workbench/consent', label: '知情同意', icon: ShieldCheck, roles: ['founder', 'chief', 'doctor'] },
  { href: '/workbench/monitor', label: '系统监控', icon: Activity, roles: ['founder', 'chief', 'engineer'] },
  { href: '/reports', label: '报告中心', icon: FileText },
  {
    href: '/admin',
    label: '管理后台',
    icon: Shield,
    roles: ['founder', 'chief'],
  },
];

export default function Sidebar() {
  const pathname = usePathname();
  const { sidebarCollapsed, toggleSidebar, user } = useAppStore();
  const userRole = user?.role || 'researcher';

  const visibleItems = NAV_ITEMS.filter(
    (item) => !item.roles || item.roles.includes(userRole)
  );

  return (
    <aside
      className={clsx(
        'flex flex-col bg-slate-900 text-slate-100 transition-all duration-200',
        sidebarCollapsed ? 'w-16' : 'w-60'
      )}
    >
      {/* Logo */}
      <div className="flex items-center justify-between h-16 px-4 border-b border-slate-700">
        {!sidebarCollapsed && (
          <div className="flex items-center gap-2">
            <Dna className="w-6 h-6 text-primary-400" />
            <span className="font-bold text-sm">AI药物设计</span>
          </div>
        )}
        <button
          onClick={toggleSidebar}
          className="p-1 rounded hover:bg-slate-700"
          aria-label="toggle sidebar"
        >
          <ChevronLeft
            className={clsx('w-4 h-4 transition-transform', sidebarCollapsed && 'rotate-180')}
          />
        </button>
      </div>

      {/* 导航 */}
      <nav className="flex-1 overflow-y-auto py-2">
        {visibleItems.map((item) => {
          const Icon = item.icon;
          const active = pathname === item.href || pathname.startsWith(item.href + '/');
          return (
            <Link
              key={item.href}
              href={item.href}
              prefetch={false}
              className={clsx(
                'flex items-center gap-3 px-4 py-2.5 text-sm transition-colors',
                'hover:bg-slate-800',
                active && 'bg-primary-600 text-white',
                sidebarCollapsed && 'justify-center'
              )}
              title={sidebarCollapsed ? item.label : undefined}
            >
              <Icon className="w-5 h-5 shrink-0" />
              {!sidebarCollapsed && <span>{item.label}</span>}
            </Link>
          );
        })}
      </nav>

      {/* 底部信息 */}
      {!sidebarCollapsed && (
        <div className="p-4 border-t border-slate-700 text-xs text-slate-400">
          <div>v1.0.0 · Mock 模式</div>
        </div>
      )}
    </aside>
  );
}
