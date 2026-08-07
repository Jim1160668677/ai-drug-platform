'use client';

/**
 * EvidenceCollectPanel — 项目证据收集面板（组件 11/18）
 *
 * 表单组件：提交 trigger_event/entity_id/extra_evidence，调用 collectEvidence。
 * 成功后复用 EvidenceResultView 展示结果。
 *
 * 端点：POST /intelligence/evidence/collect
 */
import { useState } from 'react';
import { useMutation } from '@tanstack/react-query';
import { Search, Play, RotateCcw } from 'lucide-react';
import Button from '@/components/ui/Button';
import Card from '@/components/ui/Card';
import FormError from '@/components/ui/FormError';
import EvidenceResultView from './shared/EvidenceResultView';
import { collectEvidence } from '@/lib/api';
import { toast } from '@/lib/notification';
import { useAppStore } from '@/lib/store';
import type { EvidenceResponse } from '@/types/intelligence';

export default function EvidenceCollectPanel() {
  const currentProject = useAppStore((s) => s.currentProject);
  const [triggerEvent, setTriggerEvent] = useState('');
  const [entityId, setEntityId] = useState('');
  const [extraEvidence, setExtraEvidence] = useState('');
  const [result, setResult] = useState<EvidenceResponse | null>(null);
  const [errorMsg, setErrorMsg] = useState<string | null>(null);

  const mutation = useMutation({
    mutationFn: () =>
      collectEvidence({
        project_id: currentProject?.id,
        trigger_event: triggerEvent.trim() || undefined,
        entity_id: entityId.trim() || undefined,
        extra_evidence: extraEvidence.trim() || undefined,
      }),
    onSuccess: (data) => {
      setResult(data);
      setErrorMsg(null);
      toast.success(`已收集 ${data.total_items} 项证据`);
    },
    onError: (err: unknown) => {
      const msg = err instanceof Error ? err.message : '证据收集失败';
      setErrorMsg(msg);
      toast.error('证据收集失败', msg);
    },
  });

  const handleSubmit = () => {
    if (!triggerEvent.trim() && !entityId.trim() && !extraEvidence.trim()) {
      setErrorMsg('请至少填写一项：触发事件、实体 ID 或附加证据');
      return;
    }
    mutation.mutate();
  };

  const handleReset = () => {
    setTriggerEvent('');
    setEntityId('');
    setExtraEvidence('');
    setResult(null);
    setErrorMsg(null);
  };

  return (
    <div className="space-y-3">
      <Card title="项目证据收集" action={<Search className="w-4 h-4 text-gray-400" />}>
        <div className="space-y-3">
          {/* 当前项目提示 */}
          {currentProject ? (
            <div className="px-2.5 py-1.5 bg-blue-50 rounded text-xs text-blue-600">
              当前项目: {currentProject.name}
            </div>
          ) : (
            <div className="px-2.5 py-1.5 bg-amber-50 rounded text-xs text-amber-600">
              未关联项目，将收集全局证据
            </div>
          )}

          {/* 触发事件 */}
          <div>
            <label className="block text-xs font-medium text-gray-600 mb-1">触发事件（可选）</label>
            <input
              type="text"
              value={triggerEvent}
              onChange={(e) => setTriggerEvent(e.target.value)}
              placeholder="如：靶点发现、分子优化、实验完成"
              className="w-full px-3 py-2 text-sm border border-gray-300 rounded-md focus:outline-none focus:ring-1 focus:ring-primary-500 focus:border-primary-500"
            />
          </div>

          {/* 实体 ID */}
          <div>
            <label className="block text-xs font-medium text-gray-600 mb-1">实体 ID（可选）</label>
            <input
              type="text"
              value={entityId}
              onChange={(e) => setEntityId(e.target.value)}
              placeholder="靶点/分子/数据集 ID"
              className="w-full px-3 py-2 text-sm border border-gray-300 rounded-md focus:outline-none focus:ring-1 focus:ring-primary-500 focus:border-primary-500"
            />
          </div>

          {/* 附加证据 */}
          <div>
            <label className="block text-xs font-medium text-gray-600 mb-1">附加证据（可选）</label>
            <textarea
              value={extraEvidence}
              onChange={(e) => setExtraEvidence(e.target.value)}
              placeholder="手动补充的证据文本..."
              rows={3}
              className="w-full px-3 py-2 text-sm border border-gray-300 rounded-md focus:outline-none focus:ring-1 focus:ring-primary-500 focus:border-primary-500 resize-y"
            />
          </div>

          {errorMsg && <FormError message={errorMsg} />}

          <div className="flex items-center gap-2 pt-1">
            <Button size="sm" loading={mutation.isPending} onClick={handleSubmit}>
              <Play className="w-3.5 h-3.5" />
              收集证据
            </Button>
            <Button size="sm" variant="ghost" onClick={handleReset} disabled={mutation.isPending}>
              <RotateCcw className="w-3.5 h-3.5" />
              重置
            </Button>
          </div>
        </div>
      </Card>

      {result && <EvidenceResultView data={result} />}
    </div>
  );
}