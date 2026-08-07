'use client';

/**
 * EvidenceResultView — 证据结果展示（共享子组件）
 *
 * 被 EvidenceCollectPanel（组件 11）和 EntityContextCollector（组件 12）复用。
 * 展示 evidence 文本、来源列表（source_type/count/detail）和统计。
 */
import { FileText, Database, Link2, Search, Hash } from 'lucide-react';
import clsx from 'clsx';
import Card from '@/components/ui/Card';
import EmptyState from '@/components/ui/EmptyState';
import type { EvidenceResponse } from '@/types/intelligence';

interface EvidenceResultViewProps {
  data: EvidenceResponse;
  title?: string;
}

// 来源类型 → 图标映射
const SOURCE_ICONS: Record<string, typeof FileText> = {
  dataset: Database,
  target: Search,
  molecule: Hash,
  experiment: FileText,
  link: Link2,
  default: FileText,
};

function getSourceIcon(sourceType: string): typeof FileText {
  return SOURCE_ICONS[sourceType.toLowerCase()] ?? SOURCE_ICONS.default;
}

export default function EvidenceResultView({ data, title = '证据收集结果' }: EvidenceResultViewProps) {
  if (!data) {
    return (
      <Card title={title}>
        <EmptyState title="暂无证据数据" />
      </Card>
    );
  }

  return (
    <Card
      title={title}
      action={
        <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded-full bg-blue-50 text-xs font-medium text-blue-600">
          <Hash className="w-3 h-3" />
          {data.total_items} 项
        </span>
      }
    >
      {/* 元信息条 */}
      {(data.project_id || data.entity_id || data.trigger_event) && (
        <div className="flex flex-wrap items-center gap-2 mb-3 text-xs">
          {data.project_id && (
            <span className="px-2 py-0.5 bg-gray-100 text-gray-600 rounded">
              项目: {data.project_id.slice(0, 8)}
            </span>
          )}
          {data.entity_id && (
            <span className="px-2 py-0.5 bg-purple-50 text-purple-600 rounded">
              实体: {data.entity_id.slice(0, 8)}
            </span>
          )}
          {data.trigger_event && (
            <span className="px-2 py-0.5 bg-amber-50 text-amber-600 rounded">
              触发: {data.trigger_event}
            </span>
          )}
        </div>
      )}

      {/* 证据文本 */}
      {data.text && (
        <div className="mb-4 p-3 bg-gray-50 rounded-md text-sm text-gray-700 whitespace-pre-wrap break-words">
          {data.text}
        </div>
      )}

      {/* 来源列表 */}
      {data.sources.length > 0 ? (
        <ul className="space-y-2">
          {data.sources.map((source, idx) => {
            const Icon = getSourceIcon(source.source_type);
            return (
              <li
                key={idx}
                className="flex items-start gap-2 p-2.5 border border-gray-100 rounded-md hover:bg-gray-50"
              >
                <Icon className="w-4 h-4 text-gray-400 flex-shrink-0 mt-0.5" />
                <div className="flex-1 min-w-0">
                  <div className="flex items-center gap-2 mb-0.5">
                    <span className="text-xs font-medium text-gray-700">{source.source_type}</span>
                    <span className="px-1.5 py-0.5 bg-blue-50 text-blue-600 rounded text-xs font-semibold">
                      {source.count}
                    </span>
                  </div>
                  <p className="text-xs text-gray-500 break-words line-clamp-3">{source.detail}</p>
                </div>
              </li>
            );
          })}
        </ul>
      ) : (
        !data.text && <EmptyState title="无来源数据" />
      )}
    </Card>
  );
}