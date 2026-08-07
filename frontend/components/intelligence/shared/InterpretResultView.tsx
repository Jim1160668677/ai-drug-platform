'use client';

/**
 * InterpretResultView — 解读结果展示（共享子组件）
 *
 * 被 AnalysisInterpretCard（组件 13）和 DatasetInterpretCard（组件 14）复用。
 * 展示结论、假设、建议列表、关键发现、模型/成本信息。
 */
import { Lightbulb, CheckCircle2, ListChecks, Sparkles, DollarSign, Clock, Cpu } from 'lucide-react';
import Card from '@/components/ui/Card';
import EmptyState from '@/components/ui/EmptyState';
import type { AnalysisInterpretResponse } from '@/types/intelligence';

interface InterpretResultViewProps {
  data: AnalysisInterpretResponse;
  title?: string;
}

function StatChip({ icon: Icon, label, value }: { icon: typeof DollarSign; label: string; value: string }) {
  return (
    <span className="inline-flex items-center gap-1 px-2 py-0.5 bg-gray-50 rounded text-xs text-gray-500">
      <Icon className="w-3 h-3" />
      <span>{label}:</span>
      <span className="font-medium text-gray-700">{value}</span>
    </span>
  );
}

export default function InterpretResultView({ data, title = '解读结果' }: InterpretResultViewProps) {
  if (!data) {
    return (
      <Card title={title}>
        <EmptyState title="暂无解读结果" />
      </Card>
    );
  }

  return (
    <Card title={title}>
      {/* 元信息 */}
      <div className="flex flex-wrap items-center gap-2 mb-3 pb-3 border-b border-gray-100">
        {data.intent && <StatChip icon={Sparkles} label="意图" value={data.intent} />}
        {data.model && <StatChip icon={Cpu} label="模型" value={data.model} />}
        {typeof data.cost_usd === 'number' && (
          <StatChip icon={DollarSign} label="成本" value={`$${data.cost_usd.toFixed(4)}`} />
        )}
        {typeof data.duration_sec === 'number' && (
          <StatChip icon={Clock} label="耗时" value={`${data.duration_sec.toFixed(1)}s`} />
        )}
      </div>

      {/* 结论 */}
      {data.conclusion && (
        <div className="mb-4">
          <div className="flex items-center gap-1.5 mb-1.5">
            <CheckCircle2 className="w-4 h-4 text-green-500" />
            <h4 className="text-sm font-semibold text-gray-800">结论</h4>
          </div>
          <p className="pl-5.5 text-sm text-gray-700 whitespace-pre-wrap break-words leading-relaxed">
            {data.conclusion}
          </p>
        </div>
      )}

      {/* 假设 */}
      {data.hypothesis && (
        <div className="mb-4">
          <div className="flex items-center gap-1.5 mb-1.5">
            <Lightbulb className="w-4 h-4 text-amber-500" />
            <h4 className="text-sm font-semibold text-gray-800">假设</h4>
          </div>
          <p className="pl-5.5 text-sm text-gray-700 whitespace-pre-wrap break-words leading-relaxed">
            {data.hypothesis}
          </p>
        </div>
      )}

      {/* 关键发现 */}
      {data.key_findings && data.key_findings.length > 0 && (
        <div className="mb-4">
          <div className="flex items-center gap-1.5 mb-1.5">
            <Sparkles className="w-4 h-4 text-purple-500" />
            <h4 className="text-sm font-semibold text-gray-800">关键发现 ({data.key_findings.length})</h4>
          </div>
          <ul className="pl-5.5 space-y-1">
            {data.key_findings.map((finding, idx) => (
              <li key={idx} className="text-sm text-gray-600 flex items-start gap-1.5">
                <span className="text-purple-400 mt-0.5">•</span>
                <span className="flex-1 break-words">{finding}</span>
              </li>
            ))}
          </ul>
        </div>
      )}

      {/* 建议 */}
      {data.recommendations && data.recommendations.length > 0 && (
        <div>
          <div className="flex items-center gap-1.5 mb-1.5">
            <ListChecks className="w-4 h-4 text-blue-500" />
            <h4 className="text-sm font-semibold text-gray-800">建议 ({data.recommendations.length})</h4>
          </div>
          <ol className="pl-5.5 space-y-1">
            {data.recommendations.map((rec, idx) => (
              <li key={idx} className="text-sm text-gray-600 flex items-start gap-1.5">
                <span className="text-blue-400 font-medium mt-0.5">{idx + 1}.</span>
                <span className="flex-1 break-words">{rec}</span>
              </li>
            ))}
          </ol>
        </div>
      )}
    </Card>
  );
}