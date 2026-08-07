'use client';

/**
 * AnalysisInterpretCard — 统一解读分析卡（组件 13/18）
 *
 * 表单+展示组件：输入分析问题与可选 analysis_data（JSON），
 * 调用 interpretAnalysis 获取 LLM 解读，复用 InterpretResultView 展示。
 *
 * 端点：POST /intelligence/analysis/interpret
 */
import { useState } from 'react';
import { useMutation } from '@tanstack/react-query';
import { BrainCircuit, Play, RotateCcw } from 'lucide-react';
import Button from '@/components/ui/Button';
import Card from '@/components/ui/Card';
import FormError from '@/components/ui/FormError';
import InterpretResultView from './shared/InterpretResultView';
import { interpretAnalysis } from '@/lib/api';
import { toast } from '@/lib/notification';
import { useAppStore } from '@/lib/store';
import type { AnalysisInterpretResponse } from '@/types/intelligence';

export default function AnalysisInterpretCard() {
  const currentProject = useAppStore((s) => s.currentProject);
  const [message, setMessage] = useState('');
  const [intent, setIntent] = useState('');
  const [analysisDataText, setAnalysisDataText] = useState('');
  const [result, setResult] = useState<AnalysisInterpretResponse | null>(null);
  const [errorMsg, setErrorMsg] = useState<string | null>(null);

  const mutation = useMutation({
    mutationFn: () => {
      // 解析可选的 analysis_data JSON
      let analysisData: Record<string, unknown> | null = null;
      if (analysisDataText.trim()) {
        try {
          analysisData = JSON.parse(analysisDataText);
        } catch {
          throw new Error('analysis_data 不是有效的 JSON');
        }
      }
      return interpretAnalysis({
        message: message.trim(),
        analysis_data: analysisData,
        project_id: currentProject?.id,
        intent: intent.trim() || undefined,
      });
    },
    onSuccess: (data) => {
      setResult(data);
      setErrorMsg(null);
      toast.success('解读完成');
    },
    onError: (err: unknown) => {
      const msg = err instanceof Error ? err.message : '解读失败';
      setErrorMsg(msg);
      toast.error('解读失败', msg);
    },
  });

  const handleSubmit = () => {
    if (!message.trim()) {
      setErrorMsg('请输入分析问题');
      return;
    }
    mutation.mutate();
  };

  const handleReset = () => {
    setMessage('');
    setIntent('');
    setAnalysisDataText('');
    setResult(null);
    setErrorMsg(null);
  };

  return (
    <div className="space-y-3">
      <Card title="统一解读分析" action={<BrainCircuit className="w-4 h-4 text-gray-400" />}>
        <div className="space-y-3">
          {/* 分析问题（必填） */}
          <div>
            <label className="block text-xs font-medium text-gray-600 mb-1">
              分析问题 <span className="text-red-500">*</span>
            </label>
            <textarea
              value={message}
              onChange={(e) => setMessage(e.target.value)}
              placeholder="如：这组差异表达基因暗示了什么信号通路？该分子是否适合作为先导化合物？"
              rows={3}
              className="w-full px-3 py-2 text-sm border border-gray-300 rounded-md focus:outline-none focus:ring-1 focus:ring-primary-500 focus:border-primary-500 resize-y"
            />
          </div>

          {/* 意图（可选） */}
          <div>
            <label className="block text-xs font-medium text-gray-600 mb-1">意图（可选）</label>
            <input
              type="text"
              value={intent}
              onChange={(e) => setIntent(e.target.value)}
              placeholder="如：pathway_analysis / druglikeness / mechanism"
              className="w-full px-3 py-2 text-sm border border-gray-300 rounded-md focus:outline-none focus:ring-1 focus:ring-primary-500 focus:border-primary-500"
            />
          </div>

          {/* analysis_data JSON（可选） */}
          <div>
            <label className="block text-xs font-medium text-gray-600 mb-1">
              分析数据 JSON（可选）
            </label>
            <textarea
              value={analysisDataText}
              onChange={(e) => setAnalysisDataText(e.target.value)}
              placeholder='{"genes": ["TP53", "CDK4"], "log2fc": {...}}'
              rows={4}
              className="w-full px-3 py-2 text-xs font-mono border border-gray-300 rounded-md focus:outline-none focus:ring-1 focus:ring-primary-500 focus:border-primary-500 resize-y"
            />
          </div>

          {currentProject && (
            <div className="px-2.5 py-1.5 bg-blue-50 rounded text-xs text-blue-600">
              关联项目: {currentProject.name}
            </div>
          )}

          {errorMsg && <FormError message={errorMsg} />}

          <div className="flex items-center gap-2 pt-1">
            <Button size="sm" loading={mutation.isPending} onClick={handleSubmit}>
              <Play className="w-3.5 h-3.5" />
              生成解读
            </Button>
            <Button size="sm" variant="ghost" onClick={handleReset} disabled={mutation.isPending}>
              <RotateCcw className="w-3.5 h-3.5" />
              重置
            </Button>
          </div>
        </div>
      </Card>

      {result && <InterpretResultView data={result} />}
    </div>
  );
}