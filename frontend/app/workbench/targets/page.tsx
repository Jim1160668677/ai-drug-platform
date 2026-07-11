'use client';

import { useState } from 'react';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { Search, Pill, Link2, X } from 'lucide-react';
import { getTargets, discoverTargets, repurposeTarget, buildEvidence } from '@/lib/api';
import { useAppStore } from '@/lib/store';
import Card from '@/components/ui/Card';
import Button from '@/components/ui/Button';
import Badge from '@/components/ui/Badge';

export default function TargetsPage() {
  const { currentProject } = useAppStore();
  const queryClient = useQueryClient();
  const [tier, setTier] = useState('fast_screen');
  const [showDiscover, setShowDiscover] = useState(false);
  const [gradeFilter, setGradeFilter] = useState('');
  const [detailTarget, setDetailTarget] = useState<any>(null);
  const [evidenceResult, setEvidenceResult] = useState<any>(null);
  const [evidenceGene, setEvidenceGene] = useState<string>('');

  const { data: targets, isLoading } = useQuery({
    queryKey: ['targets', currentProject?.id, gradeFilter],
    queryFn: () => getTargets(currentProject?.id, gradeFilter || undefined),
    enabled: !!currentProject,
  });

  const discoverMutation = useMutation({
    mutationFn: () =>
      discoverTargets({ projectId: currentProject!.id, tier }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['targets'] });
      setShowDiscover(false);
    },
  });

  const repurposeMutation = useMutation({
    mutationFn: (id: string) => repurposeTarget(id),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ['targets'] }),
  });

  const evidenceMutation = useMutation({
    mutationFn: (id: string) => buildEvidence(id),
    onSuccess: (res, id) => {
      const data = (res as any)?.data || res;
      setEvidenceResult(data);
      const t = targets?.find((x: any) => x.id === id);
      setEvidenceGene(t?.gene_symbol || '');
      queryClient.invalidateQueries({ queryKey: ['targets'] });
    },
  });

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold">靶点发现</h1>
          <p className="text-sm text-gray-500 mt-1">AI 辅助靶点识别 — 突变→注释→通路→证据分级</p>
        </div>
        <Button onClick={() => setShowDiscover(true)}>
          <Search className="w-4 h-4" /> 发现靶点
        </Button>
      </div>

      {/* 筛选 */}
      <div className="flex items-center gap-3 text-sm">
        <span className="text-gray-500">证据等级筛选：</span>
        <select
          value={gradeFilter}
          onChange={(e) => setGradeFilter(e.target.value)}
          className="border border-gray-300 rounded px-2 py-1"
        >
          <option value="">全部</option>
          <option value="I">I 级（已获批）</option>
          <option value="II">II 级（临床试验）</option>
          <option value="III">III 级（临床前）</option>
          <option value="IV">IV 级（推测）</option>
        </select>
      </div>

      {/* 靶点卡片网格 */}
      {isLoading ? (
        <div className="text-center py-12 text-gray-400">加载中...</div>
      ) : (
        <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
          {targets?.map((t: any) => (
            <Card key={t.id}>
              <div className="space-y-3">
                <div className="flex items-start justify-between">
                  <div>
                    <div className="text-xl font-bold text-gray-900">{t.gene_symbol}</div>
                    <div className="text-xs text-gray-500">{t.gene_name || t.description || '—'}</div>
                  </div>
                  <Badge variant="evidence" value={t.evidence_grade || 'IV'} />
                </div>

                <div>
                  <div className="flex justify-between text-xs mb-1">
                    <span className="text-gray-500">置信度</span>
                    <span className="font-medium">{((t.confidence_score || 0) * 100).toFixed(1)}%</span>
                  </div>
                  <div className="h-2 bg-gray-100 rounded-full overflow-hidden">
                    <div
                      className="h-full bg-primary-600 rounded-full"
                      style={{ width: `${(t.confidence_score || 0) * 100}%` }}
                    />
                  </div>
                </div>

                <div className="text-xs text-gray-500">
                  批准药物：{Array.isArray(t.approved_drugs) ? t.approved_drugs.length : 0} 个 · 变异：{Array.isArray(t.variant_info) ? t.variant_info.length : 0} 个
                </div>

                <div className="flex gap-2 pt-2">
                  <Button
                    size="sm"
                    variant="secondary"
                    loading={repurposeMutation.isPending}
                    onClick={() => repurposeMutation.mutate(t.id)}
                  >
                    <Pill className="w-3 h-3" /> 老药新用
                  </Button>
                  <Button
                    size="sm"
                    variant="secondary"
                    loading={evidenceMutation.isPending}
                    onClick={() => evidenceMutation.mutate(t.id)}
                  >
                    <Link2 className="w-3 h-3" /> 证据链
                  </Button>
                  <Button size="sm" variant="ghost" onClick={() => setDetailTarget(t)}>
                    详情
                  </Button>
                </div>
              </div>
            </Card>
          ))}
        </div>
      )}

      {(!targets || targets.length === 0) && !isLoading && (
        <Card>
          <div className="text-center py-12 text-gray-400">
            <Search className="w-12 h-12 mx-auto mb-2 opacity-50" />
            暂无靶点，请点击"发现靶点"
          </div>
        </Card>
      )}

      {/* 发现靶点弹窗 */}
      {showDiscover && (
        <div className="fixed inset-0 bg-black/50 flex items-center justify-center z-50 p-4">
          <div className="bg-white rounded-lg max-w-md w-full">
            <div className="flex items-center justify-between px-5 py-3 border-b">
              <h3 className="font-semibold">发现靶点</h3>
              <button onClick={() => setShowDiscover(false)}>
                <X className="w-5 h-5 text-gray-400" />
              </button>
            </div>
            <div className="p-5 space-y-4">
              <div>
                <label className="block text-sm font-medium mb-2">分析层级</label>
                <div className="space-y-2">
                  <label className="flex items-center gap-2 p-3 border rounded-md cursor-pointer hover:bg-gray-50">
                    <input
                      type="radio"
                      name="tier"
                      value="fast_screen"
                      checked={tier === 'fast_screen'}
                      onChange={(e) => setTier(e.target.value)}
                    />
                    <div>
                      <div className="text-sm font-medium">快速筛查 (fast_screen)</div>
                      <div className="text-xs text-gray-500">&lt;$5 / &lt;5min — 统计分析+规则引擎</div>
                    </div>
                  </label>
                  <label className="flex items-center gap-2 p-3 border rounded-md cursor-pointer hover:bg-gray-50">
                    <input
                      type="radio"
                      name="tier"
                      value="deep_insight"
                      checked={tier === 'deep_insight'}
                      onChange={(e) => setTier(e.target.value)}
                    />
                    <div>
                      <div className="text-sm font-medium">深度洞察 (deep_insight)</div>
                      <div className="text-xs text-gray-500">&lt;$20 / &lt;30min — LLM+RAG+网络分析</div>
                    </div>
                  </label>
                </div>
              </div>
              <Button
                className="w-full"
                loading={discoverMutation.isPending}
                onClick={() => discoverMutation.mutate()}
              >
                开始发现
              </Button>
            </div>
          </div>
        </div>
      )}

      {/* 详情抽屉 */}
      {detailTarget && (
        <div className="fixed inset-0 bg-black/50 flex items-center justify-center z-50 p-4">
          <div className="bg-white rounded-lg max-w-2xl w-full max-h-[80vh] overflow-y-auto">
            <div className="flex items-center justify-between px-5 py-3 border-b sticky top-0 bg-white">
              <h3 className="font-semibold">靶点详情 — {detailTarget.gene_symbol}</h3>
              <button onClick={() => setDetailTarget(null)}>
                <X className="w-5 h-5 text-gray-400" />
              </button>
            </div>
            <div className="p-5 space-y-4">
              <pre className="bg-gray-900 text-gray-100 p-4 rounded text-xs overflow-x-auto">
                {JSON.stringify(detailTarget, null, 2)}
              </pre>
            </div>
          </div>
        </div>
      )}

      {/* 证据链结果弹窗 */}
      {evidenceResult && (
        <div className="fixed inset-0 bg-black/50 flex items-center justify-center z-50 p-4">
          <div className="bg-white rounded-lg max-w-3xl w-full max-h-[85vh] overflow-y-auto">
            <div className="flex items-center justify-between px-5 py-3 border-b sticky top-0 bg-white">
              <h3 className="font-semibold flex items-center gap-2">
                <Link2 className="w-4 h-4" /> 证据链 — {evidenceGene || evidenceResult.root}
              </h3>
              <button onClick={() => setEvidenceResult(null)}>
                <X className="w-5 h-5 text-gray-400" />
              </button>
            </div>
            <div className="p-5 space-y-4">
              <div className="grid grid-cols-4 gap-3">
                <div className="bg-blue-50 p-3 rounded text-center">
                  <div className="text-2xl font-bold text-blue-600">{evidenceResult.total_evidence || 0}</div>
                  <div className="text-xs text-gray-500">总证据数</div>
                </div>
                <div className="bg-green-50 p-3 rounded text-center">
                  <div className="text-2xl font-bold text-green-600">{evidenceResult.grade_distribution?.I || 0}</div>
                  <div className="text-xs text-gray-500">I 级（已获批）</div>
                </div>
                <div className="bg-yellow-50 p-3 rounded text-center">
                  <div className="text-2xl font-bold text-yellow-600">{evidenceResult.grade_distribution?.II || 0}</div>
                  <div className="text-xs text-gray-500">II 级（临床试验）</div>
                </div>
                <div className="bg-orange-50 p-3 rounded text-center">
                  <div className="text-2xl font-bold text-orange-600">{(evidenceResult.grade_distribution?.III || 0) + (evidenceResult.grade_distribution?.IV || 0)}</div>
                  <div className="text-xs text-gray-500">III+IV 级</div>
                </div>
              </div>

              {evidenceResult.summary && (
                <div className="bg-gray-50 p-3 rounded text-sm text-gray-700 whitespace-pre-wrap">
                  {evidenceResult.summary}
                </div>
              )}

              <div>
                <h4 className="text-sm font-semibold mb-2">证据节点（{evidenceResult.nodes?.length || 0}）</h4>
                <div className="space-y-2 max-h-96 overflow-y-auto">
                  {evidenceResult.nodes?.map((n: any, i: number) => (
                    <div key={i} className="flex items-center gap-3 p-2 border rounded text-sm">
                      <Badge variant="evidence" value={n.grade || 'IV'} />
                      <span className="text-xs text-gray-400 uppercase">{n.type?.replace('_', ' ')}</span>
                      <span className="font-medium flex-1 truncate">{n.label}</span>
                      {n.clnsig && <span className="text-xs text-gray-500">{n.clnsig}</span>}
                      {n.indication && <span className="text-xs text-gray-500 truncate max-w-xs">{n.indication}</span>}
                      {n.phase && <span className="text-xs text-gray-500">{n.phase}</span>}
                      {n.status && <span className="text-xs text-gray-500">{n.status}</span>}
                    </div>
                  ))}
                </div>
              </div>

              {evidenceResult.edges?.length > 0 && (
                <div>
                  <h4 className="text-sm font-semibold mb-2">关系边（{evidenceResult.edges.length}）</h4>
                  <div className="text-xs text-gray-500 space-y-1 max-h-48 overflow-y-auto">
                    {evidenceResult.edges.slice(0, 20).map((e: any, i: number) => (
                      <div key={i} className="font-mono">
                        {e.source} <span className="text-blue-500">—{e.relation}→</span> {e.target} <span className="text-gray-400">({e.evidence})</span>
                      </div>
                    ))}
                    {evidenceResult.edges.length > 20 && <div className="text-gray-400">... 还有 {evidenceResult.edges.length - 20} 条</div>}
                  </div>
                </div>
              )}
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
