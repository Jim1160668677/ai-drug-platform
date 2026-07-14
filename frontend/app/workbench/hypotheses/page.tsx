'use client';

import { useState } from 'react';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { GitBranch, Plus, GitCompare, X, Play, Trash2, FileText, TrendingUp, AlertCircle, Wand2 } from 'lucide-react';
import {
  getHypotheses, createHypothesis, analyzeHypothesis, compareHypotheses,
  deleteHypothesis, eliminateHypothesis, getHypothesisDetail, autoGenerateHypotheses,
} from '@/lib/api';
import { useAppStore } from '@/lib/store';
import { toast } from '@/lib/notification';
import Card from '@/components/ui/Card';
import Button from '@/components/ui/Button';
import Badge from '@/components/ui/Badge';

export default function HypothesesPage() {
  const { currentProject } = useAppStore();
  const queryClient = useQueryClient();
  const [selected, setSelected] = useState<string[]>([]);
  const [showCreate, setShowCreate] = useState(false);
  const [compareResult, setCompareResult] = useState<any>(null);
  const [reportId, setReportId] = useState<string | null>(null);
  const [deleteTarget, setDeleteTarget] = useState<{ id: string; name: string } | null>(null);
  const [eliminateTarget, setEliminateTarget] = useState<{ id: string; name: string } | null>(null);
  const [newHyp, setNewHyp] = useState({ name: '', description: '', mechanism: '', strategy: '' });
  const [autoGenResult, setAutoGenResult] = useState<any[]>([]);
  const [showAutoGen, setShowAutoGen] = useState(false);

  const { data: hypotheses, isLoading, isError, refetch } = useQuery({
    queryKey: ['hypotheses', currentProject?.id],
    queryFn: () => getHypotheses(currentProject?.id),
    enabled: !!currentProject,
  });

  const hypList: any[] = (hypotheses as any)?.items || (Array.isArray(hypotheses) ? hypotheses : []) || [];

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
      toast.success('创建成功', '假设已创建');
    },
  });

  const analyzeMutation = useMutation({
    mutationFn: (id: string) => analyzeHypothesis(id),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['hypotheses'] });
      toast.success('分析完成', '假设分析已完成');
    },
  });

  const compareMutation = useMutation({
    mutationFn: () => compareHypotheses(currentProject!.id),
    onSuccess: (data) => setCompareResult(data),
  });

  const deleteMutation = useMutation({
    mutationFn: (id: string) => deleteHypothesis(id),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['hypotheses'] });
      toast.success('删除成功', '假设已永久删除');
    },
    onError: (err: any) => {
      toast.error('删除失败', err?.response?.data?.error?.message || '无权删除或假设不存在');
    },
  });

  const eliminateMutation = useMutation({
    mutationFn: ({ id, reason }: { id: string; reason: string }) => eliminateHypothesis(id, reason),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['hypotheses'] });
      toast.success('已淘汰', '假设已标记为淘汰');
    },
  });

  const autoGenMutation = useMutation({
    mutationFn: () => autoGenerateHypotheses(currentProject!.id, 5),
    onSuccess: (data) => {
      const hyps = Array.isArray(data) ? data : (data?.data || []);
      setAutoGenResult(hyps);
      setShowAutoGen(true);
      toast.success('生成完成', `自动生成了 ${hyps.length} 个假设`);
    },
    onError: (err: any) => {
      toast.error('生成失败', err?.response?.data?.error?.message || '请稍后重试');
    },
  });

  const toggleSelect = (id: string) => {
    setSelected((s) => (s.includes(id) ? s.filter((x) => x !== id) : [...s, id]));
  };

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold">多假设并行</h1>
          <p className="text-sm text-gray-500 mt-1">并行探索多种治疗假设 — 对比择优 · 淘汰劣选</p>
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
          <Button
            variant="primary"
            loading={autoGenMutation.isPending}
            onClick={() => autoGenMutation.mutate()}
          >
            <Wand2 className="w-4 h-4" /> 自动生成假设
          </Button>
          <Button onClick={() => setShowCreate(true)}>
            <Plus className="w-4 h-4" /> 新建假设
          </Button>
        </div>
      </div>

      {isError ? (
        <div className="rounded-xl border border-red-200 bg-red-50 p-6 text-center">
          <p className="text-sm text-red-600 mb-3">数据加载失败</p>
          <button onClick={() => refetch()} className="text-xs text-primary-600 underline">重试</button>
        </div>
      ) : isLoading ? (
        <div className="text-center py-12 text-gray-400">加载中...</div>
      ) : (
        <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
          {hypList.map((h: any, index: number) => (
            <Card key={h.id || `hyp-${index}`}>
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
                  <Badge variant={h.status === 'completed' ? 'green' : h.status === 'analyzing' ? 'blue' : h.status === 'eliminated' ? 'red' : 'gray'}>
                    {h.status === 'completed' ? '已完成' : h.status === 'analyzing' ? '分析中' : h.status === 'eliminated' ? '已淘汰' : '待分析'}
                  </Badge>
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
                      {h.analysis_result.targets && (
                        <span className="ml-2">靶点数：{h.analysis_result.targets.length}</span>
                      )}
                    </div>
                  </div>
                )}

                <div className="flex gap-1 pt-2">
                  <Button
                    size="sm"
                    variant="secondary"
                    loading={analyzeMutation.isPending}
                    onClick={() => analyzeMutation.mutate(h.id)}
                    className="flex-1"
                  >
                    <Play className="w-3 h-3" /> 分析
                  </Button>
                  <Button
                    size="sm"
                    variant="ghost"
                    onClick={() => setReportId(h.id)}
                    className="flex-1"
                  >
                    <FileText className="w-3 h-3" /> 报告
                  </Button>
                  <Button
                    size="sm"
                    variant="ghost"
                    onClick={() => setEliminateTarget({ id: h.id, name: h.name })}
                    title="淘汰此假设"
                  >
                    <AlertCircle className="w-3 h-3" />
                  </Button>
                  <Button
                    size="sm"
                    variant="ghost"
                    onClick={() => setDeleteTarget({ id: h.id, name: h.name })}
                    title="永久删除"
                  >
                    <Trash2 className="w-3 h-3" />
                  </Button>
                </div>
              </div>
            </Card>
          ))}
        </div>
      )}

      {hypList.length === 0 && !isLoading && (
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

      {/* 详细报告弹窗 */}
      {reportId && <HypothesisReport hypothesisId={reportId} onClose={() => setReportId(null)} />}

      {/* 对比结果弹窗 */}
      {compareResult && <CompareReport result={compareResult} onClose={() => setCompareResult(null)} />}

      {/* 删除确认弹窗 */}
      {deleteTarget && (
        <div className="fixed inset-0 bg-black/50 flex items-center justify-center z-50 p-4">
          <div className="bg-white rounded-lg max-w-md w-full">
            <div className="flex items-center justify-between px-5 py-3 border-b">
              <h3 className="font-semibold text-gray-900">确认删除</h3>
              <button onClick={() => setDeleteTarget(null)} className="text-gray-400 hover:text-gray-600">
                <X className="w-5 h-5" />
              </button>
            </div>
            <div className="p-5">
              <p className="text-sm text-gray-700">
                确认永久删除假设「<span className="font-medium">{deleteTarget.name}</span>」？此操作不可撤销，所有相关数据将被清除。
              </p>
              <div className="mt-4 flex justify-end gap-2">
                <Button variant="secondary" onClick={() => setDeleteTarget(null)}>取消</Button>
                <Button
                  variant="danger"
                  loading={deleteMutation.isPending}
                  onClick={() => { deleteMutation.mutate(deleteTarget.id); setDeleteTarget(null); }}
                >
                  <Trash2 className="w-4 h-4" /> 确认删除
                </Button>
              </div>
            </div>
          </div>
        </div>
      )}

      {/* 淘汰假设弹窗 */}
      {eliminateTarget && (
        <EliminateModal
          name={eliminateTarget.name}
          loading={eliminateMutation.isPending}
          onClose={() => setEliminateTarget(null)}
          onConfirm={(reason) => {
            eliminateMutation.mutate({ id: eliminateTarget.id, reason });
            setEliminateTarget(null);
          }}
        />
      )}

      {/* 自动生成假设结果弹窗 */}
      {showAutoGen && autoGenResult.length > 0 && (
        <div className="fixed inset-0 bg-black/50 flex items-center justify-center z-50 p-4">
          <div className="bg-white rounded-lg max-w-4xl w-full max-h-[85vh] overflow-y-auto">
            <div className="flex items-center justify-between px-5 py-3 border-b sticky top-0 bg-white z-10">
              <h3 className="font-semibold flex items-center gap-2">
                <Wand2 className="w-5 h-5 text-primary-600" /> 自动生成的研究假设 ({autoGenResult.length})
              </h3>
              <button onClick={() => setShowAutoGen(false)} className="text-gray-400 hover:text-gray-600">
                <X className="w-5 h-5" />
              </button>
            </div>
            <div className="p-5 space-y-4">
              {autoGenResult.map((h: any, i: number) => (
                <div key={i} className="border border-gray-200 rounded-lg p-4 hover:shadow-md transition">
                  <div className="flex items-start justify-between mb-2">
                    <h4 className="font-semibold text-gray-900">{h.title}</h4>
                    <div className="flex items-center gap-2 ml-2">
                      <span className={`px-2 py-0.5 rounded text-xs font-medium ${
                        h.confidence >= 0.7 ? 'bg-green-100 text-green-700' :
                        h.confidence >= 0.5 ? 'bg-yellow-100 text-yellow-700' :
                        'bg-red-100 text-red-700'
                      }`}>
                        置信度: {(h.confidence * 100).toFixed(0)}%
                      </span>
                      <span className="px-2 py-0.5 bg-indigo-50 text-indigo-700 rounded text-xs">
                        {h.category || 'general'}
                      </span>
                    </div>
                  </div>
                  <p className="text-sm text-gray-600 mb-3">{h.description}</p>
                  <div className="space-y-2">
                    <div>
                      <div className="text-xs font-medium text-gray-500 mb-1">支持证据</div>
                      <ul className="text-xs text-gray-600 space-y-1">
                        {(h.supporting_evidence || []).map((e: string, j: number) => (
                          <li key={j} className="flex items-start gap-1">
                            <span className="text-green-600">•</span>
                            <span>{e}</span>
                          </li>
                        ))}
                      </ul>
                    </div>
                    <div>
                      <div className="text-xs font-medium text-gray-500 mb-1">建议验证方法</div>
                      <p className="text-xs text-gray-600 bg-blue-50 p-2 rounded">{h.verification_method}</p>
                    </div>
                  </div>
                </div>
              ))}
            </div>
          </div>
        </div>
      )}
    </div>
  );
}

// ========== 假设详细报告组件 ==========
function HypothesisReport({ hypothesisId, onClose }: { hypothesisId: string; onClose: () => void }) {
  const { data, isLoading, error } = useQuery({
    queryKey: ['hypothesis-detail', hypothesisId],
    queryFn: () => getHypothesisDetail(hypothesisId),
  });

  const detail = (data as any)?.data || data;

  return (
    <div className="fixed inset-0 bg-black/50 flex items-center justify-center z-50 p-4">
      <div className="bg-white rounded-lg max-w-3xl w-full max-h-[88vh] overflow-y-auto">
        <div className="flex items-center justify-between px-5 py-3 border-b sticky top-0 bg-white z-10">
          <h3 className="font-semibold flex items-center gap-2">
            <FileText className="w-4 h-4" /> 假设详细报告
          </h3>
          <button onClick={onClose} className="text-gray-400 hover:text-gray-600">
            <X className="w-5 h-5" />
          </button>
        </div>

        {isError ? (
          <div className="rounded-xl border border-red-200 bg-red-50 p-6 text-center">
            <p className="text-sm text-red-600 mb-3">报告加载失败</p>
            <button onClick={() => refetch()} className="text-xs text-primary-600 underline">重试</button>
          </div>
        ) : isLoading ? (
          <div className="text-center py-12 text-gray-400">加载报告中...</div>
        ) : error || !detail ? (
          <div className="text-center py-12 text-red-500">加载失败，请稍后重试</div>
        ) : (
          <div className="p-5 space-y-5">
            {/* 基本信息卡片 */}
            <div className="bg-gradient-to-r from-blue-50 to-indigo-50 rounded-lg p-4 border border-blue-100">
              <h2 className="text-xl font-bold text-gray-900">{detail.name}</h2>
              <p className="text-sm text-gray-600 mt-1">{detail.description || '—'}</p>
              <div className="flex items-center gap-3 mt-2">
                <Badge variant={detail.status === 'completed' ? 'green' : detail.status === 'analyzing' ? 'blue' : detail.status === 'eliminated' ? 'red' : 'gray'}>
                  {detail.status === 'completed' ? '已完成' : detail.status === 'analyzing' ? '分析中' : detail.status === 'eliminated' ? '已淘汰' : '待分析'}
                </Badge>
                {detail.created_at && (
                  <span className="text-xs text-gray-500">创建于 {new Date(detail.created_at).toLocaleString('zh-CN')}</span>
                )}
              </div>
            </div>

            {/* 假设设计 */}
            <div>
              <h4 className="font-semibold mb-2">假设设计</h4>
              <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
                <div className="bg-gray-50 p-3 rounded">
                  <div className="text-xs text-gray-500">作用机制</div>
                  <div className="text-sm font-medium">{detail.mechanism || '—'}</div>
                </div>
                <div className="bg-gray-50 p-3 rounded">
                  <div className="text-xs text-gray-500">治疗策略</div>
                  <div className="text-sm font-medium">{detail.strategy || '—'}</div>
                </div>
              </div>
            </div>

            {/* 分析结果 */}
            {detail.analysis_result && (
              <div>
                <h4 className="font-semibold mb-2 flex items-center gap-2">
                  <TrendingUp className="w-4 h-4 text-green-600" /> 分析结果
                </h4>
                <div className="bg-gray-50 rounded-lg p-4 space-y-3">
                  {detail.analysis_result.confidence != null && (
                    <div>
                      <div className="flex justify-between text-sm mb-1">
                        <span className="text-gray-500">置信度</span>
                        <span className="font-medium">{(detail.analysis_result.confidence * 100).toFixed(1)}%</span>
                      </div>
                      <div className="h-2 bg-gray-100 rounded-full overflow-hidden">
                        <div className="h-full bg-green-500 rounded-full" style={{ width: `${detail.analysis_result.confidence * 100}%` }} />
                      </div>
                    </div>
                  )}
                  {detail.analysis_result.targets && detail.analysis_result.targets.length > 0 && (
                    <div>
                      <div className="text-sm font-medium mb-2">发现的靶点（{detail.analysis_result.targets.length}）</div>
                      <div className="space-y-2 max-h-48 overflow-y-auto">
                        {detail.analysis_result.targets.map((t: any, i: number) => (
                          <div key={i} className="flex items-center gap-3 p-2 bg-white rounded text-sm">
                            <Badge variant="evidence" value={t.evidence_grade || 'IV'} />
                            <span className="font-medium">{t.gene_symbol}</span>
                            <span className="text-xs text-gray-500 flex-1 truncate">{t.gene_name || ''}</span>
                            <span className="text-xs text-gray-500">{((t.confidence_score || 0) * 100).toFixed(0)}%</span>
                          </div>
                        ))}
                      </div>
                    </div>
                  )}
                  {detail.analysis_result.summary && (
                    <div className="text-sm text-gray-700 bg-white p-3 rounded">
                      {detail.analysis_result.summary}
                    </div>
                  )}
                </div>
              </div>
            )}

            {/* 靶点列表 */}
            {detail.target_list && detail.target_list.length > 0 && (
              <div>
                <h4 className="font-semibold mb-2">关联靶点</h4>
                <div className="flex flex-wrap gap-2">
                  {detail.target_list.map((t: string, i: number) => (
                    <span key={i} className="px-3 py-1 bg-purple-50 text-purple-700 rounded-full text-xs font-medium">
                      {t}
                    </span>
                  ))}
                </div>
              </div>
            )}

            {/* 淘汰原因 */}
            {detail.status === 'eliminated' && detail.analysis_result?.elimination_reason && (
              <div className="bg-red-50 border border-red-200 rounded-lg p-4">
                <h4 className="font-semibold text-red-900 mb-1">淘汰原因</h4>
                <p className="text-sm text-gray-700">{detail.analysis_result.elimination_reason}</p>
              </div>
            )}

            {/* 专业解读 */}
            <div className="bg-indigo-50 border border-indigo-200 rounded-lg p-4">
              <h4 className="font-semibold text-indigo-900 mb-2">专业解读</h4>
              <ul className="space-y-2">
                {generateHypothesisInterpretation(detail).map((c: string, i: number) => (
                  <li key={i} className="text-sm text-gray-700 flex items-start gap-2">
                    <span className="text-indigo-600 font-bold shrink-0">•</span>
                    <span>{c}</span>
                  </li>
                ))}
              </ul>
            </div>

            {/* 原始数据 */}
            <details className="border-t pt-3">
              <summary className="text-sm text-gray-500 cursor-pointer hover:text-gray-700">查看原始数据</summary>
              <pre className="bg-gray-900 text-gray-100 p-3 rounded text-xs overflow-x-auto mt-2">
                {JSON.stringify(detail, null, 2)}
              </pre>
            </details>
          </div>
        )}
      </div>
    </div>
  );
}

// ========== 对比报告组件 ==========
function CompareReport({ result, onClose }: { result: any; onClose: () => void }) {
  const hyps = result?.data?.hypotheses || result?.hypotheses || [];

  return (
    <div className="fixed inset-0 bg-black/50 flex items-center justify-center z-50 p-4">
      <div className="bg-white rounded-lg max-w-5xl w-full max-h-[85vh] overflow-y-auto">
        <div className="flex items-center justify-between px-5 py-3 border-b sticky top-0 bg-white z-10">
          <h3 className="font-semibold flex items-center gap-2">
            <GitCompare className="w-4 h-4" /> 假设对比报告
          </h3>
          <button onClick={onClose} className="text-gray-400 hover:text-gray-600">
            <X className="w-5 h-5" />
          </button>
        </div>

        <div className="p-5 space-y-5">
          {hyps.length === 0 ? (
            <div className="text-center py-8 text-gray-400">暂无已完成的假设可供对比</div>
          ) : (
            <>
              {/* 对比表格 */}
              <div className="overflow-x-auto">
                <table className="w-full text-sm border">
                  <thead>
                    <tr className="bg-gray-50 border-b">
                      <th className="text-left p-3">对比维度</th>
                      {hyps.map((h: any, i: number) => (
                        <th key={i} className="text-left p-3 min-w-[200px]">{h.name}</th>
                      ))}
                    </tr>
                  </thead>
                  <tbody>
                    <tr className="border-b">
                      <td className="p-3 font-medium text-gray-500">状态</td>
                      {hyps.map((h: any, i: number) => (
                        <td key={i} className="p-3">
                          <Badge variant={h.status === 'completed' ? 'green' : 'blue'}>
                            {h.status === 'completed' ? '已完成' : '分析中'}
                          </Badge>
                        </td>
                      ))}
                    </tr>
                    <tr className="border-b">
                      <td className="p-3 font-medium text-gray-500">靶点数</td>
                      {hyps.map((h: any, i: number) => (
                        <td key={i} className="p-3">{h.targets?.length || 0} 个</td>
                      ))}
                    </tr>
                    <tr className="border-b">
                      <td className="p-3 font-medium text-gray-500">靶点列表</td>
                      {hyps.map((h: any, i: number) => (
                        <td key={i} className="p-3 text-xs">
                          {(h.targets || []).join(', ') || '—'}
                        </td>
                      ))}
                    </tr>
                    <tr className="border-b">
                      <td className="p-3 font-medium text-gray-500">置信度</td>
                      {hyps.map((h: any, i: number) => (
                        <td key={i} className="p-3">
                          {h.result_summary?.confidence != null
                            ? `${(h.result_summary.confidence * 100).toFixed(1)}%`
                            : '—'}
                        </td>
                      ))}
                    </tr>
                    <tr className="border-b">
                      <td className="p-3 font-medium text-gray-500">强制深度分析</td>
                      {hyps.map((h: any, i: number) => (
                        <td key={i} className="p-3">{h.forced ? '是' : '否'}</td>
                      ))}
                    </tr>
                  </tbody>
                </table>
              </div>

              {/* 对比结论 */}
              <div className="bg-indigo-50 border border-indigo-200 rounded-lg p-4">
                <h4 className="font-semibold text-indigo-900 mb-2">对比结论</h4>
                <ul className="space-y-2">
                  {generateCompareConclusion(hyps).map((c: string, i: number) => (
                    <li key={i} className="text-sm text-gray-700 flex items-start gap-2">
                      <span className="text-indigo-600 font-bold shrink-0">•</span>
                      <span>{c}</span>
                    </li>
                  ))}
                </ul>
              </div>

              {/* 建议 */}
              <div className="bg-amber-50 border border-amber-200 rounded-lg p-4">
                <h4 className="font-semibold text-amber-900 mb-2">择优建议</h4>
                <ul className="space-y-2">
                  {generateCompareRecommendation(hyps).map((r: string, i: number) => (
                    <li key={i} className="text-sm text-gray-700 flex items-start gap-2">
                      <span className="text-amber-600 font-bold shrink-0">→</span>
                      <span>{r}</span>
                    </li>
                  ))}
                </ul>
              </div>
            </>
          )}
        </div>
      </div>
    </div>
  );
}

// ========== 淘汰确认弹窗 ==========
function EliminateModal({ name, loading, onClose, onConfirm }: {
  name: string;
  loading: boolean;
  onClose: () => void;
  onConfirm: (reason: string) => void;
}) {
  const [reason, setReason] = useState('');
  return (
    <div className="fixed inset-0 bg-black/50 flex items-center justify-center z-50 p-4">
      <div className="bg-white rounded-lg max-w-md w-full">
        <div className="flex items-center justify-between px-5 py-3 border-b">
          <h3 className="font-semibold text-gray-900">淘汰假设</h3>
          <button onClick={onClose} className="text-gray-400 hover:text-gray-600">
            <X className="w-5 h-5" />
          </button>
        </div>
        <div className="p-5 space-y-3">
          <p className="text-sm text-gray-700">
            确认淘汰假设「<span className="font-medium">{name}</span>」？淘汰后假设将标记为已淘汰状态，但数据保留。
          </p>
          <div>
            <label className="block text-sm font-medium mb-1">淘汰原因</label>
            <textarea
              value={reason}
              onChange={(e) => setReason(e.target.value)}
              className="w-full px-3 py-2 border border-gray-300 rounded-md text-sm"
              rows={3}
              placeholder="请说明淘汰原因，例如：疗效不佳、毒副作用大、证据不足等"
            />
          </div>
          <div className="flex justify-end gap-2">
            <Button variant="secondary" onClick={onClose}>取消</Button>
            <Button
              variant="danger"
              loading={loading}
              onClick={() => onConfirm(reason || '未说明原因')}
              disabled={!reason}
            >
              确认淘汰
            </Button>
          </div>
        </div>
      </div>
    </div>
  );
}

// 假设专业解读生成器
function generateHypothesisInterpretation(detail: any) {
  const interp: string[] = [];
  if (detail.status === 'completed') {
    interp.push('该假设已完成分析，分析结果可用于指导后续治疗策略制定。');
  } else if (detail.status === 'analyzing') {
    interp.push('该假设正在分析中，请稍后查看分析结果。');
  } else if (detail.status === 'eliminated') {
    interp.push('该假设已被淘汰，不建议作为治疗策略参考。');
  } else {
    interp.push('该假设尚未分析，建议点击「分析」按钮启动靶点发现流程。');
  }
  const targetCount = detail.target_list?.length || detail.analysis_result?.targets?.length || 0;
  if (targetCount > 0) {
    interp.push(`本假设识别了 ${targetCount} 个潜在靶点，建议在「治疗方案」模块中匹配对应的靶向药物和候选分子。`);
  }
  if (detail.mechanism) {
    interp.push(`作用机制为「${detail.mechanism}」，该机制${detail.mechanism.includes('抑制') ? '属于靶向抑制策略，需关注耐药突变' : detail.mechanism.includes('免疫') ? '属于免疫治疗策略，需关注免疫相关不良事件' : '需要结合具体靶点评估有效性'}。`);
  }
  if (detail.strategy) {
    interp.push(`治疗策略为「${detail.strategy}」，${detail.strategy.includes('单药') ? '单药方案安全性较好但可能面临疗效不足' : detail.strategy.includes('联合') ? '联合方案可增强疗效但需注意药物相互作用' : '建议根据患者具体情况调整'}。`);
  }
  const confidence = detail.analysis_result?.confidence;
  if (confidence != null) {
    if (confidence >= 0.7) {
      interp.push(`置信度较高（${(confidence * 100).toFixed(1)}%），该假设有较强证据支持，建议优先推进。`);
    } else if (confidence >= 0.5) {
      interp.push(`置信度中等（${(confidence * 100).toFixed(1)}%），该假设有一定证据支持，建议补充数据后评估。`);
    } else {
      interp.push(`置信度较低（${(confidence * 100).toFixed(1)}%），证据不够充分，建议谨慎参考或淘汰。`);
    }
  }
  if (interp.length === 0) {
    interp.push('暂无足够数据生成解读，请先执行分析。');
  }
  return interp;
}

// 对比结论生成器
function generateCompareConclusion(hyps: any[]) {
  const conclusions: string[] = [];
  if (hyps.length === 0) return conclusions;

  const sorted = [...hyps].sort((a, b) => {
    const ca = a.result_summary?.confidence || 0;
    const cb = b.result_summary?.confidence || 0;
    return cb - ca;
  });

  const best = sorted[0];
  conclusions.push(`共对比 ${hyps.length} 个假设，其中 ${hyps.filter(h => h.status === 'completed').length} 个已完成分析。`);

  if (best.result_summary?.confidence != null) {
    conclusions.push(`假设「${best.name}」置信度最高（${(best.result_summary.confidence * 100).toFixed(1)}%），推荐优先推进。`);
  }

  const maxTargets = Math.max(...hyps.map(h => h.targets?.length || 0));
  const hypsWithMaxTargets = hyps.filter(h => (h.targets?.length || 0) === maxTargets);
  if (maxTargets > 0) {
    conclusions.push(`假设「${hypsWithMaxTargets.map(h => h.name).join('、')}」覆盖靶点最多（${maxTargets} 个），靶点覆盖广度最大。`);
  }

  const allTargets = new Set(hyps.flatMap(h => h.targets || []));
  const commonTargets = hyps.flatMap(h => h.targets || []).filter((t: string) => hyps.every(h => (h.targets || []).includes(t)));
  if (commonTargets.length > 0) {
    conclusions.push(`共有靶点：${commonTargets.join('、')}（${commonTargets.length} 个），这些靶点在所有假设中均被识别，可靠性较高。`);
  }
  conclusions.push(`不同假设覆盖的靶点总计 ${allTargets.size} 个，靶点多样性有助于全面探索治疗机会。`);

  return conclusions;
}

// 对比建议生成器
function generateCompareRecommendation(hyps: any[]) {
  const recs: string[] = [];
  if (hyps.length === 0) return recs;

  const sorted = [...hyps].sort((a, b) => {
    const ca = a.result_summary?.confidence || 0;
    const cb = b.result_summary?.confidence || 0;
    return cb - ca;
  });

  const best = sorted[0];
  recs.push(`推荐优先推进假设「${best.name}」，其综合评估最优。`);

  if (hyps.length > 1) {
    const worst = sorted[sorted.length - 1];
    recs.push(`建议淘汰或暂缓假设「${worst.name}」，其评估指标较低，资源投入性价比不高。`);
  }

  recs.push('建议将高置信度假设的靶点接入「治疗方案」模块，匹配最优治疗组合。');
  recs.push('对于覆盖不同靶点的假设，可考虑合并靶点列表，设计联合治疗方案以覆盖更多致病通路。');
  recs.push('建议在「实验」模块中设计验证实验，通过湿实验数据进一步确认假设的可行性。');

  return recs;
}
