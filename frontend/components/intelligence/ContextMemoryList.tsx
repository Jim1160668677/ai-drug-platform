'use client';

/**
 * ContextMemoryList — 上下文记忆列表（组件 6/18）
 *
 * 按 importance 排序展示记忆条目 + context_prompt 折叠展示。
 * 端点：GET /intelligence/sessions/{id}/context
 */
import { useState } from 'react';
import { useQuery } from '@tanstack/react-query';
import { Brain, ChevronDown, ChevronRight } from 'lucide-react';
import Card from '@/components/ui/Card';
import Badge from '@/components/ui/Badge';
import EmptyState from '@/components/ui/EmptyState';
import { SkeletonList } from '@/components/ui/Skeleton';
import { getContext } from '@/lib/api';
import type { ContextMemoryItem } from '@/types/intelligence';

interface ContextMemoryListProps {
  sessionId: string;
  limit?: number;
}

const TYPE_LABELS: Record<string, string> = {
  message: '消息',
  fact: '事实',
  hypothesis: '假设',
  evidence: '证据',
  decision: '决策',
  tool_result: '工具结果',
  summary: '摘要',
};

function importanceColor(score: number): string {
  if (score >= 0.8) return 'bg-red-100 text-red-700';
  if (score >= 0.5) return 'bg-amber-100 text-amber-700';
  return 'bg-gray-100 text-gray-600';
}

export default function ContextMemoryList({ sessionId, limit = 50 }: ContextMemoryListProps) {
  const [showPrompt, setShowPrompt] = useState(false);

  const { data, isLoading } = useQuery({
    queryKey: ['intelligence-context', sessionId],
    queryFn: () => getContext(sessionId, limit),
    enabled: !!sessionId,
  });

  if (isLoading) {
    return (
      <Card title="上下文记忆">
        <SkeletonList count={3} />
      </Card>
    );
  }

  if (!data || data.memories.length === 0) {
    return (
      <Card title="上下文记忆">
        <EmptyState icon={Brain} title="暂无记忆" />
      </Card>
    );
  }

  // 按 importance 降序排序
  const sorted = [...data.memories].sort((a, b) => b.importance - a.importance);

  return (
    <Card
      title={`上下文记忆 (${data.memories.length})`}
      action={
        <span className="text-xs text-gray-400">共 {data.memories.length} 条</span>
      }
    >
      <div className="space-y-2">
        {sorted.map((item: ContextMemoryItem) => (
          <div
            key={item.id}
            className="flex items-start gap-2 p-2 rounded-md hover:bg-gray-50 transition-colors"
          >
            <Badge variant="gray" className="flex-shrink-0 text-xs">
              {TYPE_LABELS[item.type] ?? item.type}
            </Badge>
            <div className="flex-1 min-w-0">
              <p className="text-sm text-gray-700 break-words line-clamp-2">
                {typeof item.content === 'string'
                  ? item.content
                  : JSON.stringify(item.content).slice(0, 200)}
              </p>
              {item.created_at && (
                <span className="text-xs text-gray-400">
                  {new Date(item.created_at).toLocaleString('zh-CN')}
                </span>
              )}
            </div>
            <span
              className={`flex-shrink-0 px-1.5 py-0.5 rounded text-xs font-medium ${importanceColor(item.importance)}`}
              title={`重要性: ${item.importance}`}
            >
              {(item.importance * 100).toFixed(0)}%
            </span>
          </div>
        ))}
      </div>

      {/* context_prompt 折叠 */}
      {data.context_prompt && (
        <div className="mt-3 pt-3 border-t border-gray-100">
          <button
            onClick={() => setShowPrompt((v) => !v)}
            className="flex items-center gap-1 text-xs text-gray-500 hover:text-gray-700"
          >
            {showPrompt ? <ChevronDown className="w-3.5 h-3.5" /> : <ChevronRight className="w-3.5 h-3.5" />}
            上下文提示词
          </button>
          {showPrompt && (
            <pre className="mt-2 p-2 bg-gray-50 rounded text-xs text-gray-600 overflow-x-auto whitespace-pre-wrap max-h-48 overflow-y-auto">
              {data.context_prompt}
            </pre>
          )}
        </div>
      )}
    </Card>
  );
}
