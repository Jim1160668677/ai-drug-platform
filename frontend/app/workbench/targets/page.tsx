'use client';

import { useState } from 'react';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { Search, Pill, Link2, X, Dna, BookOpen, AlertCircle, Target, Shield, TrendingUp } from 'lucide-react';
import { getTargets, discoverTargets, repurposeTarget, buildEvidence } from '@/lib/api';
import { useAppStore } from '@/lib/store';
import Card from '@/components/ui/Card';
import Button from '@/components/ui/Button';
import Badge from '@/components/ui/Badge';
import ProgressBar from '@/components/ui/ProgressBar';

export default function TargetsPage() {
  const { currentProject } = useAppStore();
  const queryClient = useQueryClient();
  const [tier, setTier] = useState('fast_screen');
  const [showDiscover, setShowDiscover] = useState(false);
  const [gradeFilter, setGradeFilter] = useState('');
  const [detailTarget, setDetailTarget] = useState<any>(null);
  const [evidenceResult, setEvidenceResult] = useState<any>(null);
  const [evidenceGene, setEvidenceGene] = useState<string>('');

  const { data: targets, isLoading, isError, refetch } = useQuery({
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
    onSuccess: (res: any) => {
      const data = res?.data || res;
      const count = data?.candidates?.length || data?.count || 0;
      queryClient.invalidateQueries({ queryKey: ['targets'] });
      import('@/lib/notification').then(({ toast }) => {
        toast.success('老药新用扫描完成', `找到 ${count} 个候选药物`);
      });
    },
    onError: (err: any) => {
      import('@/lib/notification').then(({ toast }) => {
        toast.error('老药新用失败', err?.response?.data?.detail || err?.message || '请稍后重试');
      });
    },
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

      {(discoverMutation.isPending || repurposeMutation.isPending) && (
        <ProgressBar
          status="running"
          percent={50}
          message={discoverMutation.isPending ? '正在发现靶点...' : '正在分析老药新用...'}
        />
      )}

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
      {isError ? (
        <div className="rounded-xl border border-red-200 bg-red-50 p-6 text-center">
          <p className="text-sm text-red-600 mb-3">数据加载失败</p>
          <button onClick={() => refetch()} className="text-xs text-primary-600 underline">重试</button>
        </div>
      ) : isLoading ? (
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

      {/* 详情抽屉 — 专业解读报告 */}
      {detailTarget && (
        <TargetDetailReport target={detailTarget} onClose={() => setDetailTarget(null)} />
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

// ========== 靶点专业解读报告组件 ==========
function TargetDetailReport({ target, onClose }: { target: any; onClose: () => void }) {
  const grade = target.evidence_grade || 'IV';
  const confidence = (target.confidence_score || 0) * 100;
  const approvedDrugs = Array.isArray(target.approved_drugs) ? target.approved_drugs : [];
  const variants = Array.isArray(target.variant_info) ? target.variant_info : [];
  const pathways = Array.isArray(target.pathways) ? target.pathways : [];

  // 证据等级专业解读
  const gradeInfo: Record<string, { label: string; color: string; desc: string }> = {
    I: { label: 'I 级证据', color: 'green', desc: '已有获批药物靶向该基因，临床证据最充分。FDA/NMPA已批准相关药物用于特定适应症，可作为首选治疗靶点。' },
    II: { label: 'II 级证据', color: 'blue', desc: '处于临床试验阶段，已有人体数据支持其治疗潜力。可能处于I-III期临床，有望近期获批。建议关注临床试验进展。' },
    III: { label: 'III 级证据', color: 'yellow', desc: '临床前研究阶段，细胞或动物模型中已验证靶点功能。尚需人体试验确认，适合作为探索性靶点。' },
    IV: { label: 'IV 级证据', color: 'gray', desc: '推测性靶点，基于计算生物学或文献挖掘推测。需要更多实验验证，适合前沿研究探索。' },
  };
  const gi = gradeInfo[grade] || gradeInfo['IV'];

  // 生成基因功能描述
  const geneFunction = generateGeneFunction(target.gene_symbol, target.gene_name);
  // 生成临床意义
  const clinicalSignificance = generateClinicalSignificance(target, grade, approvedDrugs);
  // 生成治疗建议
  const therapeuticAdvice = generateTherapeuticAdvice(target, grade, approvedDrugs, confidence);

  return (
    <div className="fixed inset-0 bg-black/50 flex items-center justify-center z-50 p-4">
      <div className="bg-white rounded-lg max-w-3xl w-full max-h-[88vh] overflow-y-auto">
        <div className="flex items-center justify-between px-5 py-3 border-b sticky top-0 bg-white z-10">
          <h3 className="font-semibold flex items-center gap-2">
            <Dna className="w-5 h-5 text-primary-600" /> 靶点专业解读 — {target.gene_symbol}
          </h3>
          <button onClick={onClose} className="text-gray-400 hover:text-gray-600">
            <X className="w-5 h-5" />
          </button>
        </div>

        <div className="p-5 space-y-5">
          {/* 基因基本信息 */}
          <div className="bg-gradient-to-r from-blue-50 to-indigo-50 rounded-lg p-4 border border-blue-100">
            <div className="flex items-start justify-between mb-3">
              <div>
                <h2 className="text-2xl font-bold text-gray-900">{target.gene_symbol}</h2>
                <p className="text-sm text-gray-600 mt-1">{target.gene_name || target.description || geneFunction.fullName}</p>
              </div>
              <div className="flex flex-col items-end gap-2">
                <Badge variant={gi.color as any}>{gi.label}</Badge>
                <div className="text-xs text-gray-500">置信度 {confidence.toFixed(1)}%</div>
              </div>
            </div>
            <div className="h-2 bg-gray-100 rounded-full overflow-hidden">
              <div className="h-full bg-primary-600 rounded-full" style={{ width: `${confidence}%` }} />
            </div>
          </div>

          {/* 基因功能详解 */}
          <div>
            <h4 className="font-semibold mb-2 flex items-center gap-2">
              <BookOpen className="w-4 h-4 text-blue-600" /> 基因功能详解
            </h4>
            <div className="bg-gray-50 rounded-lg p-4 space-y-3 text-sm text-gray-700">
              <p>{geneFunction.description}</p>
              <div className="grid grid-cols-2 gap-3 mt-2">
                <div><span className="text-gray-500">全称：</span>{geneFunction.fullName}</div>
                <div><span className="text-gray-500">染色体定位：</span>{geneFunction.chromosome}</div>
                <div><span className="text-gray-500">蛋白家族：</span>{geneFunction.proteinFamily}</div>
                <div><span className="text-gray-500">生物学过程：</span>{geneFunction.biologicalProcess}</div>
              </div>
            </div>
          </div>

          {/* 证据等级解读 */}
          <div>
            <h4 className="font-semibold mb-2 flex items-center gap-2">
              <Shield className="w-4 h-4 text-green-600" /> 证据等级解读
            </h4>
            <div className={`rounded-lg p-4 border ${
              grade === 'I' ? 'bg-green-50 border-green-200' :
              grade === 'II' ? 'bg-blue-50 border-blue-200' :
              grade === 'III' ? 'bg-yellow-50 border-yellow-200' :
              'bg-gray-50 border-gray-200'
            }`}>
              <div className="flex items-center gap-2 mb-2">
                <Badge variant={gi.color as any}>{gi.label}</Badge>
                <span className="text-sm font-medium text-gray-700">置信度评分：{confidence.toFixed(1)}%</span>
              </div>
              <p className="text-sm text-gray-700">{gi.desc}</p>
            </div>
          </div>

          {/* 变异信息 */}
          {variants.length > 0 && (
            <div>
              <h4 className="font-semibold mb-2 flex items-center gap-2">
                <AlertCircle className="w-4 h-4 text-orange-600" /> 变异信息（{variants.length} 个）
              </h4>
              <div className="space-y-2 max-h-48 overflow-y-auto">
                {variants.map((v: any, i: number) => (
                  <div key={i} className="flex items-center gap-3 p-2 bg-gray-50 rounded text-sm">
                    {v.clnsig && <Badge variant="purple">{v.clnsig}</Badge>}
                    <span className="font-mono text-xs flex-1 truncate">{v.hgvs || v.name || v.variant || JSON.stringify(v).slice(0, 60)}</span>
                    {v.indication && <span className="text-xs text-gray-500 truncate max-w-xs">{v.indication}</span>}
                  </div>
                ))}
              </div>
            </div>
          )}

          {/* 获批药物 */}
          {approvedDrugs.length > 0 && (
            <div>
              <h4 className="font-semibold mb-2 flex items-center gap-2">
                <Pill className="w-4 h-4 text-green-600" /> 获批药物（{approvedDrugs.length} 个）
              </h4>
              <div className="space-y-2">
                {approvedDrugs.map((drug: any, i: number) => (
                  <div key={i} className="flex items-center gap-3 p-3 bg-green-50 rounded-lg">
                    <div className="w-8 h-8 rounded-full bg-green-100 flex items-center justify-center">
                      <Pill className="w-4 h-4 text-green-700" />
                    </div>
                    <div className="flex-1">
                      <div className="text-sm font-medium text-gray-900">{drug.name || drug}</div>
                      {(drug.indication || drug.phase) && (
                        <div className="text-xs text-gray-500">
                          {drug.indication && <span>适应症：{drug.indication}</span>}
                          {drug.indication && drug.phase && <span> · </span>}
                          {drug.phase && <span>阶段：{drug.phase}</span>}
                        </div>
                      )}
                    </div>
                  </div>
                ))}
              </div>
            </div>
          )}

          {/* 相关通路 */}
          {pathways.length > 0 && (
            <div>
              <h4 className="font-semibold mb-2 flex items-center gap-2">
                <Target className="w-4 h-4 text-purple-600" /> 相关信号通路
              </h4>
              <div className="flex flex-wrap gap-2">
                {pathways.map((p: any, i: number) => (
                  <span key={i} className="px-3 py-1 bg-purple-50 text-purple-700 rounded-full text-xs font-medium">
                    {typeof p === 'string' ? p : p.name || p.pathway || JSON.stringify(p).slice(0, 40)}
                  </span>
                ))}
              </div>
            </div>
          )}

          {/* 临床意义 */}
          <div className="bg-indigo-50 border border-indigo-200 rounded-lg p-4">
            <h4 className="font-semibold text-indigo-900 mb-2 flex items-center gap-2">
              <TrendingUp className="w-4 h-4" /> 临床意义
            </h4>
            <ul className="space-y-2">
              {clinicalSignificance.map((c: string, i: number) => (
                <li key={i} className="text-sm text-gray-700 flex items-start gap-2">
                  <span className="text-indigo-600 font-bold shrink-0">•</span>
                  <span>{c}</span>
                </li>
              ))}
            </ul>
          </div>

          {/* 治疗建议 */}
          <div className="bg-amber-50 border border-amber-200 rounded-lg p-4">
            <h4 className="font-semibold text-amber-900 mb-2">治疗策略建议</h4>
            <ul className="space-y-2">
              {therapeuticAdvice.map((a: string, i: number) => (
                <li key={i} className="text-sm text-gray-700 flex items-start gap-2">
                  <span className="text-amber-600 font-bold shrink-0">→</span>
                  <span>{a}</span>
                </li>
              ))}
            </ul>
          </div>
        </div>
      </div>
    </div>
  );
}

// 基因功能知识库（常见靶点）
const GENE_KNOWLEDGE: Record<string, any> = {
  EGFR: {
    fullName: 'Epidermal Growth Factor Receptor',
    chromosome: '7p11.2',
    proteinFamily: '受体酪氨酸激酶（RTK）家族 / ErbB 家族',
    biologicalProcess: '细胞增殖、分化、存活和迁移',
    description: 'EGFR 是表皮生长因子受体家族成员，是一种跨膜糖蛋白，具有酪氨酸激酶活性。EGFR 的过度表达或激活突变在非小细胞肺癌（NSCLC）、结直肠癌、胶质母细胞瘤等多种实体瘤中常见，是肿瘤精准治疗最重要的靶点之一。EGFR 突变（如外显子19缺失、L858R 点突变）导致激酶结构性激活，促进肿瘤细胞无限增殖。针对 EGFR 的靶向药物（吉非替尼、厄洛替尼、奥希替尼等）已彻底改变 NSCLC 的治疗格局。',
  },
  KRAS: {
    fullName: 'KRAS Proto-Oncogene, GTPase',
    chromosome: '12p12.1',
    proteinFamily: 'RAS 小 GTP 酶超家族',
    biologicalProcess: '细胞信号转导、增殖和分化',
    description: 'KRAS 是 RAS 基因家族成员，编码 GTP 酶蛋白，在 MAPK/ERK 信号通路中起关键开关作用。KRAS 突变（G12C、G12D、G12V 等）在胰腺癌（~90%）、结直肠癌（~40%）、肺癌（~25%）中高频出现，导致 RAS-RAF-MEK-ERK 通路持续激活。曾被认为是"不可成药"靶点，近年来 Sotorasib（AMG 510）和 Adagrasib（MRTX849）等 KRAS G12C 抑制剂的成功开发突破了这一瓶颈。',
  },
  TP53: {
    fullName: 'Tumor Protein P53',
    chromosome: '17p13.1',
    proteinFamily: 'p53 转录因子家族',
    biologicalProcess: 'DNA损伤修复、细胞周期调控、凋亡',
    description: 'TP53 被称为"基因组守护者"，是最重要的抑癌基因之一。编码 p53 蛋白，在 DNA 损伤时激活下游靶基因，引起细胞周期停滞、DNA 修复或凋亡。TP53 突变见于约 50% 的人类肿瘤，多数为错义突变导致功能丧失。TP53 突变通常预示较差预后，目前靶向策略包括基因治疗、合成致死药物和 p53 重新激活剂。',
  },
  B7H3: {
    fullName: 'CD276 Molecule',
    chromosome: '9p24.1',
    proteinFamily: 'B7 免疫共刺激/共抑制分子家族',
    biologicalProcess: '免疫调节、T细胞共刺激/共抑制',
    description: 'B7-H3（CD276）是 B7 家族成员，在多种肿瘤中高表达，包括神经母细胞瘤、肺癌、前列腺癌等。B7-H3 具有免疫共抑制功能，可抑制 T 细胞活化，帮助肿瘤逃避免疫监视。目前针对 B7-H3 的治疗策略包括抗体药物偶联物（ADC）、双特异性抗体、CAR-T 细胞疗法等，是肿瘤免疫治疗的新兴靶点。',
  },
  PD_L1: {
    fullName: 'Programmed Cell Death 1 Ligand 1',
    chromosome: '9p24.1',
    proteinFamily: 'B7 免疫检查点分子家族',
    biologicalProcess: '免疫检查点、T细胞抑制',
    description: 'PD-L1（CD274）是 PD-1 的配体，在肿瘤微环境中高表达。PD-L1 与 PD-1 结合后抑制 T 细胞活化，导致肿瘤免疫逃逸。抗 PD-L1 抗体（阿替利珠单抗、度伐利尤单抗、阿维鲁单抗）通过阻断 PD-1/PD-L1 相互作用恢复抗肿瘤免疫，已在多种肿瘤中获批。PD-L1 表达水平常作为免疫治疗疗效的预测生物标志物。',
  },
  VEGF: {
    fullName: 'Vascular Endothelial Growth Factor',
    chromosome: '6p21.1',
    proteinFamily: 'PDGF 超家族 / VEGF 家族',
    biologicalProcess: '血管生成、血管通透性',
    description: 'VEGF 是肿瘤血管生成的关键驱动因子，通过结合 VEGFR（血管内皮生长因子受体）促进肿瘤新生血管形成。抗 VEGF 治疗（贝伐珠单抗、雷莫西尤单抗）和 VEGFR 酪氨酸激酶抑制剂（索拉非尼、舒尼替尼、仑伐替尼）广泛用于多种实体瘤治疗，通过切断肿瘤血供抑制生长。',
  },
  BRAF: {
    fullName: 'B-Raf Proto-Oncogene, Serine/Threonine Kinase',
    chromosome: '7q34',
    proteinFamily: 'RAF 丝氨酸/苏氨酸激酶家族',
    biologicalProcess: 'MAPK 信号通路、细胞增殖',
    description: 'BRAF 编码丝氨酸/苏氨酸激酶，在 RAS-RAF-MEK-ERK 通路中处于 RAS 下游。BRAF V600E 突变在黑色素瘤（~50%）、甲状腺癌、结直肠癌中常见，导致激酶结构性激活。BRAF 抑制剂（维莫非尼、达拉非尼、恩非替尼）联合 MEK 抑制剂已成为 BRAF V600E 突变肿瘤的标准治疗方案。',
  },
  ALK: {
    fullName: 'Anaplastic Lymphoma Receptor Tyrosine Kinase',
    chromosome: '2p23.2',
    proteinFamily: '胰岛素受体超家族 / 受体酪氨酸激酶',
    biologicalProcess: '神经发育、细胞增殖',
    description: 'ALK 基因融合（如 EML4-ALK）在非小细胞肺癌（3-7%）中是重要驱动基因。ALK 融合蛋白具有结构性激酶活性，持续激活下游信号通路。ALK 抑制剂（克唑替尼、阿来替尼、洛拉替尼）对 ALK 阳性 NSCLC 患者疗效显著，5 年生存率大幅提升。耐药后可序贯使用新一代 ALK 抑制剂。',
  },
  HER2: {
    fullName: 'Erb-B2 Receptor Tyrosine Kinase 2',
    chromosome: '17q12',
    proteinFamily: 'ErbB 受体酪氨酸激酶家族',
    biologicalProcess: '细胞增殖、分化',
    description: 'HER2（ErbB2）是 ErbB 受体家族成员。HER2 过表达/扩增见于乳腺癌（15-20%）、胃癌等。抗 HER2 治疗（曲妥珠单抗、帕妥珠单抗、T-DXd）显著改善了 HER2 阳性患者的预后。近年来 HER2 低表达乳腺癌的靶向治疗也取得突破。',
  },
  MET: {
    fullName: 'MET Proto-Oncogene, Receptor Tyrosine Kinase',
    chromosome: '7q31.2',
    proteinFamily: '受体酪氨酸激酶家族',
    biologicalProcess: '细胞迁移、侵袭、血管生成',
    description: 'MET 基因编码肝细胞生长因子受体（HGFR）。MET 外显子14跳突、MET 扩增和 MET 融合是 NSCLC 等肿瘤的驱动事件。MET 抑制剂（卡马替尼、特泊替尼、赛沃替尼）对 MET 外显子14跳突患者疗效显著。MET 扩增也是 EGFR-TKI 耐药的重要机制之一。',
  },
};

function generateGeneFunction(symbol: string, name?: string) {
  const known = GENE_KNOWLEDGE[symbol?.toUpperCase()];
  if (known) return known;
  return {
    fullName: name || `${symbol} 基因`,
    chromosome: '未收录',
    proteinFamily: '待进一步注释',
    biologicalProcess: '待功能注释',
    description: `${symbol} 是一个被识别为潜在药物靶点的基因。该基因的详细功能信息尚在收集中，建议结合文献数据库（PubMed、ClinVar、COSMIC）和通路数据库（KEGG、Reactome）进一步了解其生物学功能和疾病关联。当前基于多组学数据和AI模型推断其具有治疗潜力，建议进行体外实验验证。`,
  };
}

function generateClinicalSignificance(target: any, grade: string, approvedDrugs: any[]) {
  const sig: string[] = [];
  if (grade === 'I') {
    sig.push(`${target.gene_symbol} 已有 ${approvedDrugs.length} 个获批药物，是经过充分临床验证的治疗靶点，可直接用于临床治疗决策。`);
  } else if (grade === 'II') {
    sig.push(`${target.gene_symbol} 处于临床试验阶段，具有较高的转化价值。建议关注相关临床试验招募信息，可为患者提供新药治疗机会。`);
  } else if (grade === 'III') {
    sig.push(`${target.gene_symbol} 在临床前模型中显示治疗潜力，但尚需人体试验验证。适合作为探索性治疗靶点，建议开展研究者发起的临床试验（IIT）。`);
  } else {
    sig.push(`${target.gene_symbol} 基于计算生物学推断为潜在靶点，需要更多实验数据支持。建议先进行体外和体内验证实验。`);
  }
  const conf = (target.confidence_score || 0) * 100;
  if (conf >= 80) {
    sig.push(`AI 模型置信度高达 ${conf.toFixed(1)}%，多源证据一致性高，靶点可靠性強。`);
  } else if (conf >= 60) {
    sig.push(`AI 模型置信度 ${conf.toFixed(1)}%，证据中等可信，建议结合多维度数据综合评估。`);
  } else {
    sig.push(`AI 模型置信度 ${conf.toFixed(1)}%，证据尚不充分，建议补充更多组学数据提高预测可靠性。`);
  }
  const variantCount = Array.isArray(target.variant_info) ? target.variant_info.length : 0;
  if (variantCount > 0) {
    sig.push(`检出 ${variantCount} 个相关变异，部分变异可能具有临床意义，建议进行 ACMG 分级和药物敏感性分析。`);
  }
  return sig;
}

function generateTherapeuticAdvice(target: any, grade: string, approvedDrugs: any[], confidence: number) {
  const advice: string[] = [];
  if (grade === 'I' && approvedDrugs.length > 0) {
    advice.push(`优先考虑已获批的 ${approvedDrugs.length} 种靶向药物，根据患者基因检测结果选择敏感药物。`);
    advice.push('建议进行药物基因组学检测，评估个体代谢差异，优化给药方案。');
  } else if (grade === 'II') {
    advice.push('建议查询符合入组条件的临床试验，为患者提供前沿治疗机会。');
    advice.push('关注同靶点药物的跨适应症研究，探索老药新用可能性。');
  } else {
    advice.push('建议先进行体外细胞实验和动物模型验证，确认靶点成药性。');
    advice.push('可探索联合用药策略，与已有靶向药物联用增强疗效。');
  }
  if (confidence >= 70) {
    advice.push(`置信度较高（${confidence.toFixed(1)}%），建议优先推进该靶点的分子设计和治疗方案匹配。`);
  } else {
    advice.push(`置信度 ${confidence.toFixed(1)}%，建议补充更多验证数据后再投入大量研发资源。`);
  }
  advice.push('在「分子库」模块中根据该靶点设计候选分子，并在「治疗方案」模块中匹配最优治疗组合。');
  return advice;
}
