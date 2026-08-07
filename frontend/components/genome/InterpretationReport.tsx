'use client';

import { BookOpen, FileText, AlertTriangle, Lightbulb, Bot } from 'lucide-react';
import Badge from '@/components/ui/Badge';

interface InterpretationReportProps {
  /** LLM 解读结果（结构化 JSON） */
  interpretation: any;
  /** 是否加载中 */
  loading?: boolean;
}

export default function InterpretationReport({
  interpretation,
  loading,
}: InterpretationReportProps) {
  if (loading) {
    return (
      <div className="space-y-3">
        <div className="h-6 w-1/3 animate-pulse rounded bg-gray-100" />
        <div className="h-20 w-full animate-pulse rounded bg-gray-100" />
        <div className="h-20 w-full animate-pulse rounded bg-gray-100" />
      </div>
    );
  }

  if (!interpretation) {
    return (
      <div className="rounded-lg border border-dashed border-gray-300 bg-gray-50 p-6 text-center text-sm text-gray-500">
        <FileText className="w-10 h-10 mx-auto mb-2 text-gray-400" />
        暂未生成解读报告，点击「生成 LLM 解读」按钮
      </div>
    );
  }

  const llmModel: string = interpretation.llm_model || '';
  const isFallback = llmModel === 'rule_fallback' || interpretation.fallback === true;

  // 兼容两种结构：① {summary, mechanism, action_items, disclaimer} ② {interpretation: {...}}
  const inner = interpretation.interpretation || interpretation;
  const summary = inner.summary || interpretation.summary || '';
  const mechanism = inner.mechanism || interpretation.mechanism || '';
  const actionItems = inner.action_items || interpretation.action_items || [];
  const disclaimer =
    inner.disclaimer || interpretation.disclaimer || '本报告仅供科研参考，不构成医疗建议';

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between flex-wrap gap-2">
        <div className="flex items-center gap-2">
          <BookOpen className="w-4 h-4 text-primary-600" />
          <h3 className="text-sm font-semibold text-gray-900">AI 解读报告</h3>
        </div>
        <div className="flex items-center gap-2">
          {llmModel && (
            <Badge variant="purple">
              <span className="flex items-center gap-1">
                <Bot className="w-3 h-3" />
                {llmModel}
              </span>
            </Badge>
          )}
          {isFallback && (
            <Badge variant="yellow" value="规则降级" />
          )}
        </div>
      </div>

      {summary && (
        <div className="rounded-lg border border-gray-200 bg-white p-4">
          <div className="text-xs font-medium text-gray-500 mb-1">综合结论</div>
          <div className="text-sm text-gray-800 whitespace-pre-wrap">{summary}</div>
        </div>
      )}

      {mechanism && (
        <div className="rounded-lg border border-blue-200 bg-blue-50/50 p-4">
          <div className="flex items-center gap-1 text-xs font-medium text-blue-600 mb-1">
            <Lightbulb className="w-3.5 h-3.5" />
            机制解读
          </div>
          <div className="text-sm text-gray-700 whitespace-pre-wrap">{mechanism}</div>
        </div>
      )}

      {actionItems && actionItems.length > 0 && (
        <div className="rounded-lg border border-green-200 bg-green-50/50 p-4">
          <div className="flex items-center gap-1 text-xs font-medium text-green-700 mb-2">
            <Lightbulb className="w-3.5 h-3.5" />
            行动建议
          </div>
          <ul className="space-y-1.5">
            {actionItems.map((item: any, idx: number) => (
              <li key={idx} className="text-sm text-gray-700 flex items-start gap-2">
                <span className="text-green-600 mt-0.5">•</span>
                <span className="whitespace-pre-wrap">
                  {typeof item === 'string' ? item : item?.content || item?.text || JSON.stringify(item)}
                </span>
              </li>
            ))}
          </ul>
        </div>
      )}

      <div className="flex items-start gap-2 rounded-lg bg-yellow-50 border border-yellow-200 p-3 text-xs text-yellow-800">
        <AlertTriangle className="w-4 h-4 shrink-0 mt-0.5" />
        <span>{disclaimer}</span>
      </div>
    </div>
  );
}
