'use client';

/**
 * SessionMetaCard — 会话元信息卡（组件 2/18）
 *
 * 展示会话的标题、状态、模式、消息数、最后消息时间、上下文摘要。
 * 端点：GET /intelligence/sessions/{id}
 */
import { useQuery } from '@tanstack/react-query';
import { Clock, MessageCircle, Activity, Brain } from 'lucide-react';
import Card from '@/components/ui/Card';
import Badge from '@/components/ui/Badge';
import { SkeletonCard } from '@/components/ui/Skeleton';
import { getSession } from '@/lib/api';
import type { PrimaryMode } from '@/types/intelligence';

interface SessionMetaCardProps {
  sessionId: string;
  onModeChange?: () => void;
}

const MODE_META: Record<string, { label: string; icon: typeof Brain; color: string }> = {
  chat: { label: '问答', icon: MessageCircle, color: 'text-blue-600' },
  reasoning: { label: '推理', icon: Brain, color: 'text-purple-600' },
  agent: { label: 'Agent', icon: Activity, color: 'text-green-600' },
  hybrid: { label: '混合', icon: Activity, color: 'text-amber-600' },
  auto: { label: '自动', icon: Activity, color: 'text-gray-600' },
};

function formatTime(ts?: string | null): string {
  if (!ts) return '—';
  try {
    const d = new Date(ts);
    return d.toLocaleString('zh-CN', { month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit' });
  } catch {
    return ts;
  }
}

export default function SessionMetaCard({ sessionId }: SessionMetaCardProps) {
  const { data: session, isLoading } = useQuery({
    queryKey: ['intelligence-session', sessionId],
    queryFn: () => getSession(sessionId),
    enabled: !!sessionId,
  });

  if (isLoading) {
    return <SkeletonCard />;
  }

  if (!session) {
    return null;
  }

  const modeMeta = MODE_META[session.primary_mode] ?? MODE_META.auto;
  const ModeIcon = modeMeta.icon;

  return (
    <Card>
      <div className="flex items-start justify-between gap-3">
        <div className="flex-1 min-w-0">
          <div className="flex items-center gap-2 mb-1">
            <h2 className="text-base font-semibold text-gray-900 truncate">
              {session.title}
            </h2>
            <Badge variant="status" value={session.status} />
          </div>
          <div className="flex items-center gap-3 text-xs text-gray-500">
            <span className="flex items-center gap-1">
              <ModeIcon className={`w-3.5 h-3.5 ${modeMeta.color}`} />
              {modeMeta.label}模式
            </span>
            <span className="flex items-center gap-1">
              <MessageCircle className="w-3.5 h-3.5" />
              {session.message_count} 条消息
            </span>
            <span className="flex items-center gap-1">
              <Clock className="w-3.5 h-3.5" />
              {formatTime(session.last_message_at)}
            </span>
          </div>
        </div>
      </div>

      {/* 上下文摘要 */}
      {session.context && Object.keys(session.context).length > 0 && (
        <div className="mt-3 pt-3 border-t border-gray-100">
          <p className="text-xs text-gray-400 mb-1">上下文摘要</p>
          <div className="flex flex-wrap gap-1.5">
            {Object.entries(session.context).slice(0, 8).map(([key, val]) => (
              <span
                key={key}
                className="inline-flex items-center px-2 py-0.5 rounded bg-gray-100 text-xs text-gray-600"
              >
                {key}: {typeof val === 'object' ? JSON.stringify(val).slice(0, 30) : String(val).slice(0, 30)}
              </span>
            ))}
          </div>
        </div>
      )}
    </Card>
  );
}
