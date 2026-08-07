'use client';

/**
 * EntityContextCollector — 实体上下文收集器（组件 12/18）
 *
 * 表单组件：输入 entity_id，调用 collectEntityContext 收集该实体的上下文证据。
 * 成功后复用 EvidenceResultView 展示结果。
 *
 * 端点：POST /intelligence/evidence/collect-entity
 */
import { useState } from 'react';
import { useMutation } from '@tanstack/react-query';
import { Crosshair, Play, RotateCcw } from 'lucide-react';
import Button from '@/components/ui/Button';
import Card from '@/components/ui/Card';
import FormError from '@/components/ui/FormError';
import EvidenceResultView from './shared/EvidenceResultView';
import { collectEntityContext } from '@/lib/api';
import { toast } from '@/lib/notification';
import { useAppStore } from '@/lib/store';
import type { EvidenceResponse } from '@/types/intelligence';

export default function EntityContextCollector() {
  const currentProject = useAppStore((s) => s.currentProject);
  const [entityId, setEntityId] = useState('');
  const [triggerEvent, setTriggerEvent] = useState('');
  const [result, setResult] = useState<EvidenceResponse | null>(null);
  const [errorMsg, setErrorMsg] = useState<string | null>(null);

  const mutation = useMutation({
    mutationFn: () =>
      collectEntityContext({
        project_id: currentProject?.id,
        entity_id: entityId.trim(),
        trigger_event: triggerEvent.trim() || undefined,
      }),
    onSuccess: (data) => {
      setResult(data);
      setErrorMsg(null);
      toast.success(`已收集实体 ${entityId.slice(0, 8)} 的 ${data.total_items} 项上下文`);
    },
    onError: (err: unknown) => {
      const msg = err instanceof Error ? err.message : '实体上下文收集失败';
      setErrorMsg(msg);
      toast.error('实体上下文收集失败', msg);
    },
  });

  const handleSubmit = () => {
    if (!entityId.trim()) {
      setErrorMsg('请输入实体 ID');
      return;
    }
    mutation.mutate();
  };

  const handleReset = () => {
    setEntityId('');
    setTriggerEvent('');
    setResult(null);
    setErrorMsg(null);
  };

  return (
    <div className="space-y-3">
      <Card title="实体上下文收集" action={<Crosshair className="w-4 h-4 text-gray-400" />}>
        <div className="space-y-3">
          {/* 实体 ID（必填） */}
          <div>
            <label className="block text-xs font-medium text-gray-600 mb-1">
              实体 ID <span className="text-red-500">*</span>
            </label>
            <input
              type="text"
              value={entityId}
              onChange={(e) => setEntityId(e.target.value)}
              placeholder="靶点/分子/数据集/实验 ID"
              className="w-full px-3 py-2 text-sm border border-gray-300 rounded-md focus:outline-none focus:ring-1 focus:ring-primary-500 focus:border-primary-500"
            />
          </div>

          {/* 触发事件 */}
          <div>
            <label className="block text-xs font-medium text-gray-600 mb-1">触发事件（可选）</label>
            <input
              type="text"
              value={triggerEvent}
              onChange={(e) => setTriggerEvent(e.target.value)}
              placeholder="如：差异表达分析、分子对接、实验验证"
              className="w-full px-3 py-2 text-sm border border-gray-300 rounded-md focus:outline-none focus:ring-1 focus:ring-primary-500 focus:border-primary-500"
            />
          </div>

          {/* 项目提示 */}
          {currentProject && (
            <div className="px-2.5 py-1.5 bg-blue-50 rounded text-xs text-blue-600">
              关联项目: {currentProject.name}
            </div>
          )}

          {errorMsg && <FormError message={errorMsg} />}

          <div className="flex items-center gap-2 pt-1">
            <Button size="sm" loading={mutation.isPending} onClick={handleSubmit}>
              <Play className="w-3.5 h-3.5" />
              收集上下文
            </Button>
            <Button size="sm" variant="ghost" onClick={handleReset} disabled={mutation.isPending}>
              <RotateCcw className="w-3.5 h-3.5" />
              重置
            </Button>
          </div>
        </div>
      </Card>

      {result && <EvidenceResultView data={result} title="实体上下文证据" />}
    </div>
  );
}