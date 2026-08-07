'use client';

/**
 * MultimodalNormalizerPanel — 多模态数据标准化面板（组件 15/18）
 *
 * 表单组件：输入文本、图片 URL/Base64、结构化数据 JSON，
 * 调用 normalizeMultimodal 将多模态输入标准化为统一文本表示。
 *
 * 端点：POST /intelligence/multimodal/normalize
 */
import { useState } from 'react';
import { useMutation } from '@tanstack/react-query';
import { Layers, Play, RotateCcw, Image as ImageIcon, FileText, Code2 } from 'lucide-react';
import Button from '@/components/ui/Button';
import Card from '@/components/ui/Card';
import FormError from '@/components/ui/FormError';
import EmptyState from '@/components/ui/EmptyState';
import { normalizeMultimodal } from '@/lib/api';
import { toast } from '@/lib/notification';
import type { MultimodalNormalizeResponse } from '@/types/intelligence';

export default function MultimodalNormalizerPanel() {
  const [text, setText] = useState('');
  const [imageUrls, setImageUrls] = useState('');
  const [imageBase64, setImageBase64] = useState('');
  const [structuredDataText, setStructuredDataText] = useState('');
  const [result, setResult] = useState<MultimodalNormalizeResponse | null>(null);
  const [errorMsg, setErrorMsg] = useState<string | null>(null);

  const mutation = useMutation({
    mutationFn: () => {
      const urls = imageUrls
        .split('\n')
        .map((s) => s.trim())
        .filter(Boolean);
      const b64 = imageBase64
        .split('\n')
        .map((s) => s.trim())
        .filter(Boolean);

      let structuredData: Record<string, unknown> | undefined;
      if (structuredDataText.trim()) {
        try {
          structuredData = JSON.parse(structuredDataText);
        } catch {
          throw new Error('structured_data 不是有效的 JSON');
        }
      }

      return normalizeMultimodal({
        text: text.trim() || undefined,
        image_urls: urls.length > 0 ? urls : undefined,
        image_base64: b64.length > 0 ? b64 : undefined,
        structured_data: structuredData,
      });
    },
    onSuccess: (data) => {
      setResult(data);
      setErrorMsg(null);
      toast.success(`已标准化 ${data.modalities.length} 种模态`);
    },
    onError: (err: unknown) => {
      const msg = err instanceof Error ? err.message : '多模态标准化失败';
      setErrorMsg(msg);
      toast.error('多模态标准化失败', msg);
    },
  });

  const handleSubmit = () => {
    if (!text.trim() && !imageUrls.trim() && !imageBase64.trim() && !structuredDataText.trim()) {
      setErrorMsg('请至少提供一种模态输入');
      return;
    }
    mutation.mutate();
  };

  const handleReset = () => {
    setText('');
    setImageUrls('');
    setImageBase64('');
    setStructuredDataText('');
    setResult(null);
    setErrorMsg(null);
  };

  return (
    <div className="space-y-3">
      <Card title="多模态标准化" action={<Layers className="w-4 h-4 text-gray-400" />}>
        <div className="space-y-3">
          {/* 文本输入 */}
          <div>
            <label className="flex items-center gap-1 text-xs font-medium text-gray-600 mb-1">
              <FileText className="w-3 h-3" /> 文本（可选）
            </label>
            <textarea
              value={text}
              onChange={(e) => setText(e.target.value)}
              placeholder="输入文本内容..."
              rows={2}
              className="w-full px-3 py-2 text-sm border border-gray-300 rounded-md focus:outline-none focus:ring-1 focus:ring-primary-500 focus:border-primary-500 resize-y"
            />
          </div>

          {/* 图片 URL */}
          <div>
            <label className="flex items-center gap-1 text-xs font-medium text-gray-600 mb-1">
              <ImageIcon className="w-3 h-3" /> 图片 URL（每行一个，可选）
            </label>
            <textarea
              value={imageUrls}
              onChange={(e) => setImageUrls(e.target.value)}
              placeholder={"https://example.com/image1.png\nhttps://example.com/image2.png"}
              rows={2}
              className="w-full px-3 py-2 text-sm border border-gray-300 rounded-md focus:outline-none focus:ring-1 focus:ring-primary-500 focus:border-primary-500 resize-y"
            />
          </div>

          {/* 图片 Base64 */}
          <div>
            <label className="flex items-center gap-1 text-xs font-medium text-gray-600 mb-1">
              <ImageIcon className="w-3 h-3" /> 图片 Base64（每行一个，可选）
            </label>
            <textarea
              value={imageBase64}
              onChange={(e) => setImageBase64(e.target.value)}
              placeholder="data:image/png;base64,..."
              rows={2}
              className="w-full px-3 py-2 text-xs font-mono border border-gray-300 rounded-md focus:outline-none focus:ring-1 focus:ring-primary-500 focus:border-primary-500 resize-y"
            />
          </div>

          {/* 结构化数据 JSON */}
          <div>
            <label className="flex items-center gap-1 text-xs font-medium text-gray-600 mb-1">
              <Code2 className="w-3 h-3" /> 结构化数据 JSON（可选）
            </label>
            <textarea
              value={structuredDataText}
              onChange={(e) => setStructuredDataText(e.target.value)}
              placeholder='{"key": "value", "list": [1, 2, 3]}'
              rows={3}
              className="w-full px-3 py-2 text-xs font-mono border border-gray-300 rounded-md focus:outline-none focus:ring-1 focus:ring-primary-500 focus:border-primary-500 resize-y"
            />
          </div>

          {errorMsg && <FormError message={errorMsg} />}

          <div className="flex items-center gap-2 pt-1">
            <Button size="sm" loading={mutation.isPending} onClick={handleSubmit}>
              <Play className="w-3.5 h-3.5" />
              标准化
            </Button>
            <Button size="sm" variant="ghost" onClick={handleReset} disabled={mutation.isPending}>
              <RotateCcw className="w-3.5 h-3.5" />
              重置
            </Button>
          </div>
        </div>
      </Card>

      {/* 结果展示 */}
      {result && (
        <Card title="标准化结果">
          <div className="space-y-3">
            {/* 模态标签 */}
            <div className="flex flex-wrap items-center gap-2">
              <span className="text-xs text-gray-500">模态:</span>
              {result.modalities.map((m) => (
                <span key={m} className="px-2 py-0.5 bg-purple-50 text-purple-600 rounded text-xs font-medium">
                  {m}
                </span>
              ))}
              {result.has_image && (
                <span className="px-2 py-0.5 bg-blue-50 text-blue-600 rounded text-xs font-medium">
                  含图像
                </span>
              )}
            </div>

            {/* 主文本 */}
            {result.primary_text && (
              <div>
                <p className="text-xs font-medium text-gray-600 mb-1">主文本</p>
                <p className="p-2.5 bg-gray-50 rounded text-sm text-gray-700 whitespace-pre-wrap break-words">
                  {result.primary_text}
                </p>
              </div>
            )}

            {/* 文本化结果 */}
            {result.textualized && (
              <div>
                <p className="text-xs font-medium text-gray-600 mb-1">文本化输出</p>
                <p className="p-2.5 bg-green-50 rounded text-sm text-gray-700 whitespace-pre-wrap break-words">
                  {result.textualized}
                </p>
              </div>
            )}

            {/* items 详情 */}
            {result.items.length > 0 && (
              <div>
                <p className="text-xs font-medium text-gray-600 mb-1">条目 ({result.items.length})</p>
                <pre className="p-2.5 bg-gray-50 rounded text-xs text-gray-600 overflow-x-auto max-h-48">
                  {JSON.stringify(result.items, null, 2)}
                </pre>
              </div>
            )}
          </div>
        </Card>
      )}

      {!result && !mutation.isPending && (
        <Card title="标准化结果">
          <EmptyState title="提交后在此查看结果" />
        </Card>
      )}
    </div>
  );
}