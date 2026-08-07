'use client';

/**
 * DatasetInterpretCard — 数据集解读卡（组件 14/18）
 *
 * 表单+展示组件：输入 dataset_id 与可选问题，调用 interpretDataset 获取解读。
 * 复用 InterpretResultView 展示结果。
 *
 * 端点：POST /intelligence/analysis/datasets/{id}/interpret
 */
import { useState } from 'react';
import { useMutation } from '@tanstack/react-query';
import { Database, Play, RotateCcw } from 'lucide-react';
import Button from '@/components/ui/Button';
import Card from '@/components/ui/Card';
import FormError from '@/components/ui/FormError';
import InterpretResultView from './shared/InterpretResultView';
import { interpretDataset } from '@/lib/api';
import { toast } from '@/lib/notification';
import { useAppStore } from '@/lib/store';
import type { AnalysisInterpretResponse } from '@/types/intelligence';

export default function DatasetInterpretCard() {
  const currentProject = useAppStore((s) => s.currentProject);
  const [datasetId, setDatasetId] = useState('');
  const [message, setMessage] = useState('');
  const [result, setResult] = useState<AnalysisInterpretResponse | null>(null);
  const [errorMsg, setErrorMsg] = useState<string | null>(null);

  const mutation = useMutation({
    mutationFn: () =>
      interpretDataset(datasetId.trim(), {
        message: message.trim() || undefined,
        project_id: currentProject?.id,
      }),
    onSuccess: (data) => {
      setResult(data);
      setErrorMsg(null);
      toast.success('数据集解读完成');
    },
    onError: (err: unknown) => {
      const msg = err instanceof Error ? err.message : '数据集解读失败';
      setErrorMsg(msg);
      toast.error('数据集解读失败', msg);
    },
  });

  const handleSubmit = () => {
    if (!datasetId.trim()) {
      setErrorMsg('请输入数据集 ID');
      return;
    }
    mutation.mutate();
  };

  const handleReset = () => {
    setDatasetId('');
    setMessage('');
    setResult(null);
    setErrorMsg(null);
  };

  return (
    <div className="space-y-3">
      <Card title="数据集解读" action={<Database className="w-4 h-4 text-gray-400" />}>
        <div className="space-y-3">
          {/* 数据集 ID（必填） */}
          <div>
            <label className="block text-xs font-medium text-gray-600 mb-1">
              数据集 ID <span className="text-red-500">*</span>
            </label>
            <input
              type="text"
              value={datasetId}
              onChange={(e) => setDatasetId(e.target.value)}
              placeholder="输入数据集 ID（UUID）"
              className="w-full px-3 py-2 text-sm border border-gray-300 rounded-md focus:outline-none focus:ring-1 focus:ring-primary-500 focus:border-primary-500"
            />
          </div>

          {/* 解读问题（可选） */}
          <div>
            <label className="block text-xs font-medium text-gray-600 mb-1">解读问题（可选）</label>
            <textarea
              value={message}
              onChange={(e) => setMessage(e.target.value)}
              placeholder="留空则由系统自动生成解读；或输入具体问题，如：该数据集的差异表达基因富集在哪些通路？"
              rows={3}
              className="w-full px-3 py-2 text-sm border border-gray-300 rounded-md focus:outline-none focus:ring-1 focus:ring-primary-500 focus:border-primary-500 resize-y"
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
              解读数据集
            </Button>
            <Button size="sm" variant="ghost" onClick={handleReset} disabled={mutation.isPending}>
              <RotateCcw className="w-3.5 h-3.5" />
              重置
            </Button>
          </div>
        </div>
      </Card>

      {result && <InterpretResultView data={result} title="数据集解读结果" />}
    </div>
  );
}