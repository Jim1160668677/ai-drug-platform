'use client';

import { useState } from 'react';
import { useMutation, useQuery } from '@tanstack/react-query';
import { submitFeedback, getRun } from '@/lib/api';
import type { FeedbackType } from '@/types/coscientist';
import { Loader2, MessageSquarePlus, Send, History, CheckCircle, AlertCircle } from 'lucide-react';

const FEEDBACK_TYPES: { value: FeedbackType; label: string; color: string }[] = [
  { value: 'constraint', label: '约束', color: 'border-amber-300 bg-amber-50 text-amber-700' },
  { value: 'approval', label: '认可', color: 'border-green-300 bg-green-50 text-green-700' },
  { value: 'rejection', label: '否决', color: 'border-red-300 bg-red-50 text-red-700' },
  { value: 'new_evidence', label: '新证据', color: 'border-blue-300 bg-blue-50 text-blue-700' },
];

export default function ExpertFeedbackPanel({ runId }: { runId: string }) {
  const [feedbackText, setFeedbackText] = useState('');
  const [feedbackType, setFeedbackType] = useState<FeedbackType>('constraint');
  const [targetHypothesisId, setTargetHypothesisId] = useState('');

  // 获取运行信息（检查状态和已有反馈）
  const { data: run } = useQuery({
    queryKey: ['coscientist-run', runId],
    queryFn: () => getRun(runId),
    enabled: !!runId,
    refetchInterval: 5000,
  });

  const canSubmit = run?.status === 'running' || run?.status === 'awaiting_feedback';

  const mutation = useMutation({
    mutationFn: () =>
      submitFeedback(runId, {
        feedback_text: feedbackText,
        feedback_type: feedbackType,
        target_hypothesis_id: targetHypothesisId || undefined,
      }),
    onSuccess: () => {
      setFeedbackText('');
      setTargetHypothesisId('');
    },
  });

  const handleSubmit = () => {
    if (!feedbackText.trim()) return;
    mutation.mutate();
  };

  const feedbackHistory = run?.expert_feedback ?? [];

  return (
    <div className="space-y-4">
      <div className="flex items-center gap-2 mb-2">
        <MessageSquarePlus className="w-4 h-4 text-indigo-500" />
        <h3 className="text-sm font-semibold text-gray-700">专家反馈</h3>
        {run?.status === 'awaiting_feedback' && (
          <span className="text-xs px-2 py-0.5 bg-amber-100 text-amber-700 rounded-full animate-pulse">
            等待您的反馈
          </span>
        )}
      </div>

      {/* 反馈输入 */}
      <div className={`p-4 bg-white border rounded-lg space-y-3 ${canSubmit ? 'border-gray-200' : 'border-gray-100 opacity-60'}`}>
        {!canSubmit && (
          <div className="text-xs text-gray-400 flex items-center gap-1">
            <AlertCircle className="w-3 h-3" />
            运行未在进行中，无法提交反馈
          </div>
        )}

        {/* 反馈类型 */}
        <div>
          <label className="text-xs font-medium text-gray-500 mb-1.5 block">反馈类型</label>
          <div className="flex gap-2 flex-wrap">
            {FEEDBACK_TYPES.map((ft) => (
              <button
                key={ft.value}
                onClick={() => setFeedbackType(ft.value)}
                disabled={!canSubmit}
                className={`px-3 py-1 text-xs border rounded-full transition ${
                  feedbackType === ft.value
                    ? ft.color + ' font-medium'
                    : 'border-gray-200 text-gray-500 hover:border-gray-300'
                }`}
              >
                {ft.label}
              </button>
            ))}
          </div>
        </div>

        {/* 目标假设 */}
        <div>
          <label className="text-xs font-medium text-gray-500 mb-1.5 block">
            目标假设 ID（可选）
          </label>
          <input
            type="text"
            value={targetHypothesisId}
            onChange={(e) => setTargetHypothesisId(e.target.value)}
            placeholder="留空表示对所有假设"
            disabled={!canSubmit}
            className="w-full px-3 py-1.5 text-sm border border-gray-200 rounded-lg focus:ring-1 focus:ring-indigo-500 focus:border-transparent"
          />
        </div>

        {/* 反馈文本 */}
        <div>
          <label className="text-xs font-medium text-gray-500 mb-1.5 block">反馈内容</label>
          <textarea
            value={feedbackText}
            onChange={(e) => setFeedbackText(e.target.value)}
            placeholder="例如：请重点关注 BMP 通路相关的假设，排除已临床验证的靶点..."
            disabled={!canSubmit}
            className="w-full p-2.5 text-sm border border-gray-200 rounded-lg resize-y min-h-[80px] focus:ring-1 focus:ring-indigo-500 focus:border-transparent"
            maxLength={10000}
          />
        </div>

        <button
          onClick={handleSubmit}
          disabled={!canSubmit || !feedbackText.trim() || mutation.isPending}
          className="w-full py-2 px-4 bg-indigo-600 text-white rounded-lg text-sm font-medium flex items-center justify-center gap-2 disabled:opacity-50 disabled:cursor-not-allowed hover:bg-indigo-700 transition"
        >
          {mutation.isPending ? (
            <>
              <Loader2 className="w-3.5 h-3.5 animate-spin" />
              提交中...
            </>
          ) : (
            <>
              <Send className="w-3.5 h-3.5" />
              提交反馈
            </>
          )}
        </button>

        {mutation.isSuccess && (
          <div className="text-xs text-green-600 flex items-center gap-1">
            <CheckCircle className="w-3 h-3" />
            反馈已提交，将在下一轮迭代中应用
          </div>
        )}
        {mutation.isError && (
          <div className="text-xs text-red-600">
            提交失败：{(mutation.error as any)?.response?.data?.error?.message ?? '未知错误'}
          </div>
        )}
      </div>

      {/* 反馈历史 */}
      {feedbackHistory.length > 0 && (
        <div>
          <div className="flex items-center gap-1.5 text-xs font-medium text-gray-500 mb-2">
            <History className="w-3.5 h-3.5" />
            反馈历史（{feedbackHistory.length} 条）
          </div>
          <div className="space-y-1.5">
            {feedbackHistory.map((fb, i) => (
              <div key={i} className="p-2 bg-gray-50 border border-gray-200 rounded text-xs">
                <div className="flex items-center justify-between mb-1">
                  <span className="font-medium text-gray-600">
                    {(fb as any).feedback_type ?? '反馈'}
                  </span>
                  {(fb as any).round != null && (
                    <span className="text-gray-400">第 {(fb as any).round} 轮</span>
                  )}
                </div>
                <p className="text-gray-600">{(fb as any).feedback_text ?? (fb as any).raw_feedback ?? JSON.stringify(fb)}</p>
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}
