'use client';

/**
 * VisionAnalyzerCard — 视觉内容解析卡（组件 16/18）
 *
 * 表单+展示组件：输入图片 data URI 与解析 prompt，调用 analyzeVision 获取描述。
 * 支持 pathology/protein_structure/molecule_structure/chart/general 五类分析。
 *
 * 端点：POST /intelligence/vision/analyze
 */
import { useState } from 'react';
import { useMutation } from '@tanstack/react-query';
import { Eye, Play, RotateCcw, DollarSign, Clock, Cpu, Image as ImageIcon } from 'lucide-react';
import Button from '@/components/ui/Button';
import Card from '@/components/ui/Card';
import FormError from '@/components/ui/FormError';
import EmptyState from '@/components/ui/EmptyState';
import { analyzeVision } from '@/lib/api';
import { toast } from '@/lib/notification';
import type { VisionAnalyzeResponse, VisionAnalysisType } from '@/types/intelligence';

const ANALYSIS_TYPES: Array<{ value: VisionAnalysisType; label: string }> = [
  { value: 'general', label: '通用' },
  { value: 'pathology', label: '病理切片' },
  { value: 'protein_structure', label: '蛋白结构' },
  { value: 'molecule_structure', label: '分子结构' },
  { value: 'chart', label: '图表' },
];

export default function VisionAnalyzerCard() {
  const [imageDataUri, setImageDataUri] = useState('');
  const [prompt, setPrompt] = useState('');
  const [analysisType, setAnalysisType] = useState<VisionAnalysisType>('general');
  const [focus, setFocus] = useState('');
  const [result, setResult] = useState<VisionAnalyzeResponse | null>(null);
  const [errorMsg, setErrorMsg] = useState<string | null>(null);

  const mutation = useMutation({
    mutationFn: () =>
      analyzeVision({
        image_data_uri: imageDataUri.trim(),
        prompt: prompt.trim(),
        analysis_type: analysisType,
        focus: focus.trim() || undefined,
      }),
    onSuccess: (data) => {
      setResult(data);
      setErrorMsg(null);
      toast.success('视觉解析完成');
    },
    onError: (err: unknown) => {
      const msg = err instanceof Error ? err.message : '视觉解析失败';
      setErrorMsg(msg);
      toast.error('视觉解析失败', msg);
    },
  });

  const handleSubmit = () => {
    if (!imageDataUri.trim()) {
      setErrorMsg('请输入图片 data URI');
      return;
    }
    if (!prompt.trim()) {
      setErrorMsg('请输入解析提示词');
      return;
    }
    mutation.mutate();
  };

  const handleReset = () => {
    setImageDataUri('');
    setPrompt('');
    setAnalysisType('general');
    setFocus('');
    setResult(null);
    setErrorMsg(null);
  };

  return (
    <div className="space-y-3">
      <Card title="视觉内容解析" action={<Eye className="w-4 h-4 text-gray-400" />}>
        <div className="space-y-3">
          {/* 图片预览 */}
          {imageDataUri.trim() && (
            <div className="flex justify-center p-2 bg-gray-50 rounded">
              {/* eslint-disable-next-line @next/next/no-img-element */}
              <img
                src={imageDataUri.trim()}
                alt="预览"
                className="max-h-32 object-contain rounded"
                onError={(e) => {
                  (e.target as HTMLImageElement).style.display = 'none';
                }}
              />
            </div>
          )}

          {/* 图片 data URI */}
          <div>
            <label className="flex items-center gap-1 text-xs font-medium text-gray-600 mb-1">
              <ImageIcon className="w-3 h-3" /> 图片 data URI <span className="text-red-500">*</span>
            </label>
            <textarea
              value={imageDataUri}
              onChange={(e) => setImageDataUri(e.target.value)}
              placeholder="data:image/png;base64,..."
              rows={3}
              className="w-full px-3 py-2 text-xs font-mono border border-gray-300 rounded-md focus:outline-none focus:ring-1 focus:ring-primary-500 focus:border-primary-500 resize-y"
            />
          </div>

          {/* 解析类型 */}
          <div>
            <label className="block text-xs font-medium text-gray-600 mb-1">解析类型</label>
            <select
              value={analysisType}
              onChange={(e) => setAnalysisType(e.target.value as VisionAnalysisType)}
              className="w-full px-3 py-2 text-sm border border-gray-300 rounded-md focus:outline-none focus:ring-1 focus:ring-primary-500 focus:border-primary-500 bg-white"
            >
              {ANALYSIS_TYPES.map((t) => (
                <option key={t.value} value={t.value}>
                  {t.label}
                </option>
              ))}
            </select>
          </div>

          {/* 解析提示词 */}
          <div>
            <label className="block text-xs font-medium text-gray-600 mb-1">
              解析提示词 <span className="text-red-500">*</span>
            </label>
            <textarea
              value={prompt}
              onChange={(e) => setPrompt(e.target.value)}
              placeholder="如：描述这张病理切片中的细胞形态特征"
              rows={2}
              className="w-full px-3 py-2 text-sm border border-gray-300 rounded-md focus:outline-none focus:ring-1 focus:ring-primary-500 focus:border-primary-500 resize-y"
            />
          </div>

          {/* 关注焦点 */}
          <div>
            <label className="block text-xs font-medium text-gray-600 mb-1">关注焦点（可选）</label>
            <input
              type="text"
              value={focus}
              onChange={(e) => setFocus(e.target.value)}
              placeholder="如：细胞核形态、蛋白二级结构"
              className="w-full px-3 py-2 text-sm border border-gray-300 rounded-md focus:outline-none focus:ring-1 focus:ring-primary-500 focus:border-primary-500"
            />
          </div>

          {errorMsg && <FormError message={errorMsg} />}

          <div className="flex items-center gap-2 pt-1">
            <Button size="sm" loading={mutation.isPending} onClick={handleSubmit}>
              <Play className="w-3.5 h-3.5" />
              解析图片
            </Button>
            <Button size="sm" variant="ghost" onClick={handleReset} disabled={mutation.isPending}>
              <RotateCcw className="w-3.5 h-3.5" />
              重置
            </Button>
          </div>
        </div>
      </Card>

      {/* 结果展示 */}
      {result ? (
        <Card title="解析结果">
          <div className="space-y-3">
            {/* 元信息 */}
            <div className="flex flex-wrap items-center gap-2 pb-2 border-b border-gray-100">
              {result.model && (
                <span className="inline-flex items-center gap-1 px-2 py-0.5 bg-gray-50 rounded text-xs text-gray-500">
                  <Cpu className="w-3 h-3" /> {result.model}
                </span>
              )}
              {typeof result.cost_usd === 'number' && (
                <span className="inline-flex items-center gap-1 px-2 py-0.5 bg-gray-50 rounded text-xs text-gray-500">
                  <DollarSign className="w-3 h-3" /> ${result.cost_usd.toFixed(4)}
                </span>
              )}
              {typeof result.duration_sec === 'number' && (
                <span className="inline-flex items-center gap-1 px-2 py-0.5 bg-gray-50 rounded text-xs text-gray-500">
                  <Clock className="w-3 h-3" /> {result.duration_sec.toFixed(1)}s
                </span>
              )}
            </div>

            {/* 描述 */}
            <p className="text-sm text-gray-700 whitespace-pre-wrap break-words leading-relaxed">
              {result.description}
            </p>

            {/* usage 详情 */}
            {result.usage && Object.keys(result.usage).length > 0 && (
              <details className="text-xs">
                <summary className="cursor-pointer text-gray-400 hover:text-gray-600">Token 用量</summary>
                <pre className="mt-1 p-2 bg-gray-50 rounded overflow-x-auto">
                  {JSON.stringify(result.usage, null, 2)}
                </pre>
              </details>
            )}
          </div>
        </Card>
      ) : (
        !mutation.isPending && (
          <Card title="解析结果">
            <EmptyState title="提交后在此查看结果" />
          </Card>
        )
      )}
    </div>
  );
}