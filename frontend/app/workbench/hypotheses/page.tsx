'use client';

import { useState } from 'react';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { GitBranch, Plus, GitCompare, X, Play } from 'lucide-react';
import { getHypotheses, createHypothesis, analyzeHypothesis, compareHypotheses } from '@/lib/api';
import { useAppStore } from '@/lib/store';
import Card from '@/components/ui/Card';
import Button from '@/components/ui/Button';
import Badge from '@/components/ui/Badge';

export default function HypothesesPage() {
  const { currentProject } = useAppStore();
  const queryClient = useQueryClient();
  const [selected, setSelected] = useState<string[]>([]);
  const [showCreate, setShowCreate] = useState(false);
  const [compareResult, setCompareResult] = useState<any>(null);
  const [newHyp, setNewHyp] = useState({ name: '', description: '', mechanism: '', strategy: '' });

  const { data: hypotheses, isLoading } = useQuery({
    queryKey: ['hypotheses', currentProject?.id],
    queryFn: () => getHypotheses(currentProject?.id),
    enabled: !!currentProject,
  });

  const createMutation = useMutation({
    mutationFn: () =>
      createHypothesis(
        {
          name: newHyp.name,
          description: newHyp.description,
          mechanism: newHyp.mechanism,
          strategy: newHyp.strategy,
        },
        currentProject!.id
      ),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['hypotheses'] });
      setShowCreate(false);
      setNewHyp({ name: '', description: '', mechanism: '', strategy: '' });
    },
  });

  const analyzeMutation = useMutation({
    mutationFn: (id: string) => analyzeHypothesis(id),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ['hypotheses'] }),
  });

  const compareMutation = useMutation({
    mutationFn: () => compareHypotheses(currentProject!.id),
    onSuccess: (data) => setCompareResult(data),
  });

  const toggleSelect = (id: string) => {
    setSelected((s) => (s.includes(id) ? s.filter((x) => x !== id) : [...s, id]));
  };

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold">多假设并行</h1>
          <p className="text-sm text-gray-500 mt-1">并行探索多种治疗假设 — 对比择优</p>
        </div>
        <div className="flex gap-2">
          <Button
            variant="secondary"
            disabled={selected.length < 2}
            loading={compareMutation.isPending}
            onClick={() => compareMutation.mutate()}
          >
            <GitCompare className="w-4 h-4" /> 对比 ({selected.length})
          </Button>
          <Button onClick={() => setShowCreate(true)}>
            <Plus className="w-4 h-4" /> 新建假设
          </Button>
        </div>
      </div>

      {isLoading ? (
        <div className="text-center py-12 text-gray-400">加载中...</div>
      ) : (
        <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
          {hypotheses?.map((h: any) => (
            <Card key={h.id}>
              <div className="space-y-3">
                <div className="flex items-start justify-between">
                  <div className="flex items-center gap-2">
                    <input
                      type="checkbox"
                      checked={selected.includes(h.id)}
                      onChange={() => toggleSelect(h.id)}
                      className="w-4 h-4"
                    />
                    <div className="text-lg font-bold">{h.name}</div>
                  </div>
                  <Badge variant="status" value={h.status || 'planned'} />
                </div>

                <p className="text-sm text-gray-600">{h.description}</p>

                <div className="text-xs space-y-1">
                  <div><span className="text-gray-500">机制：</span>{h.mechanism || '—'}</div>
                  <div><span className="text-gray-500">策略：</span>{h.strategy || '—'}</div>
                  <div><span className="text-gray-500">靶点：</span>{(h.target_list || []).join(', ') || '—'}</div>
                </div>

                {h.analysis_result && (
                  <div className="bg-gray-50 p-2 rounded text-xs">
                    <div className="font-medium mb-1">分析结果</div>
                    <div className="text-gray-600">
                      置信度：{h.analysis_result.confidence?.toFixed(2) || '—'}
                    </div>
                  </div>
                )}

                <Button
                  size="sm"
                  variant="secondary"
                  loading={analyzeMutation.isPending}
                  onClick={() => analyzeMutation.mutate(h.id)}
                  className="w-full"
                >
                  <Play className="w-3 h-3" /> 分析
                </Button>
              </div>
            </Card>
          ))}
        </div>
      )}

      {(!hypotheses || hypotheses.length === 0) && !isLoading && (
        <Card>
          <div className="text-center py-12 text-gray-400">
            <GitBranch className="w-12 h-12 mx-auto mb-2 opacity-50" />
            暂无假设，请点击"新建假设"
          </div>
        </Card>
      )}

      {/* 新建假设弹窗 */}
      {showCreate && (
        <div className="fixed inset-0 bg-black/50 flex items-center justify-center z-50 p-4">
          <div className="bg-white rounded-lg max-w-md w-full">
            <div className="flex items-center justify-between px-5 py-3 border-b">
              <h3 className="font-semibold">新建假设</h3>
              <button onClick={() => setShowCreate(false)}>
                <X className="w-5 h-5 text-gray-400" />
              </button>
            </div>
            <div className="p-5 space-y-3">
              <div>
                <label className="block text-sm font-medium mb-1">假设名称</label>
                <input
                  type="text"
                  value={newHyp.name}
                  onChange={(e) => setNewHyp((s) => ({ ...s, name: e.target.value }))}
                  className="w-full px-3 py-2 border border-gray-300 rounded-md text-sm"
                  placeholder="例如：H1 - EGFR 通路抑制"
                />
              </div>
              <div>
                <label className="block text-sm font-medium mb-1">描述</label>
                <textarea
                  value={newHyp.description}
                  onChange={(e) => setNewHyp((s) => ({ ...s, description: e.target.value }))}
                  className="w-full px-3 py-2 border border-gray-300 rounded-md text-sm"
                  rows={2}
                />
              </div>
              <div>
                <label className="block text-sm font-medium mb-1">机制</label>
                <input
                  type="text"
                  value={newHyp.mechanism}
                  onChange={(e) => setNewHyp((s) => ({ ...s, mechanism: e.target.value }))}
                  className="w-full px-3 py-2 border border-gray-300 rounded-md text-sm"
                  placeholder="例如：酪氨酸激酶抑制"
                />
              </div>
              <div>
                <label className="block text-sm font-medium mb-1">策略</label>
                <input
                  type="text"
                  value={newHyp.strategy}
                  onChange={(e) => setNewHyp((s) => ({ ...s, strategy: e.target.value }))}
                  className="w-full px-3 py-2 border border-gray-300 rounded-md text-sm"
                  placeholder="例如：第三代 TKI 单药"
                />
              </div>
              <Button
                className="w-full"
                loading={createMutation.isPending}
                onClick={() => createMutation.mutate()}
                disabled={!newHyp.name}
              >
                创建
              </Button>
            </div>
          </div>
        </div>
      )}

      {/* 对比结果弹窗 */}
      {compareResult && (
        <div className="fixed inset-0 bg-black/50 flex items-center justify-center z-50 p-4">
          <div className="bg-white rounded-lg max-w-4xl w-full max-h-[80vh] overflow-y-auto">
            <div className="flex items-center justify-between px-5 py-3 border-b sticky top-0 bg-white">
              <h3 className="font-semibold">假设对比</h3>
              <button onClick={() => setCompareResult(null)}>
                <X className="w-5 h-5 text-gray-400" />
              </button>
            </div>
            <div className="p-5">
              <pre className="bg-gray-900 text-gray-100 p-4 rounded text-xs overflow-x-auto">
                {JSON.stringify(compareResult, null, 2)}
              </pre>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
