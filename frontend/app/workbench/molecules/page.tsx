'use client';

import { useState, useEffect } from 'react';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { Atom, X, FlaskConical, Plus, Gauge, Microscope, ScanSearch, Trash2, Zap, BookOpen, Target as TargetIcon, Link2 } from 'lucide-react';
import {
  getMolecules, designMolecule, assessDruglikeness,
  predictProperties, explainMolecule, deleteMolecule, getTargets,
  designMultiTargetMolecules,
} from '@/lib/api';
import { optimizeTreatments } from '@/lib/api';
import { useAppStore } from '@/lib/store';
import { toast } from '@/lib/notification';
import Card from '@/components/ui/Card';
import Button from '@/components/ui/Button';
import Badge from '@/components/ui/Badge';
import PlotlyChart from '@/components/charts/PlotlyChart';
import ProgressBar from '@/components/ui/ProgressBar';

export default function MoleculesPage() {
  const { currentProject } = useAppStore();
  const [detail, setDetail] = useState<any>(null);
  const [showDesign, setShowDesign] = useState(false);
  const [showAssess, setShowAssess] = useState(false);
  const [assessResult, setAssessResult] = useState<any>(null);
  const [designResult, setDesignResult] = useState<any>(null);
  const [showAdmet, setShowAdmet] = useState(false);
  const [showExplain, setShowExplain] = useState(false);
  const [admetResult, setAdmetResult] = useState<any>(null);
  const [explainResult, setExplainResult] = useState<any>(null);
  const [showMultiTarget, setShowMultiTarget] = useState(false);
  const [multiTargetResult, setMultiTargetResult] = useState<any>(null);
  const [deleteTarget, setDeleteTarget] = useState<{ id: string; name: string } | null>(null);
  const [autoDesignProgress, setAutoDesignProgress] = useState<string>('');
  const [detailAdmet, setDetailAdmet] = useState<any>(null);
  const [detailExplain, setDetailExplain] = useState<any>(null);
  const [detailAdmetLoading, setDetailAdmetLoading] = useState(false);
  const [detailExplainLoading, setDetailExplainLoading] = useState(false);
  const [autoMatchResult, setAutoMatchResult] = useState<any>(null);
  const [autoMatchLoading, setAutoMatchLoading] = useState(false);
  const queryClient = useQueryClient();

  const { data: molecules, isLoading, isError, refetch } = useQuery({
    queryKey: ['molecules'],
    queryFn: () => getMolecules(),
  });

  const designMutation = useMutation({
    mutationFn: (payload: any) => designMolecule(payload),
    onSuccess: (res) => {
      const data = (res as any)?.data || res;
      setDesignResult(data);
      queryClient.invalidateQueries({ queryKey: ['molecules'] });
    },
  });

  const assessMutation = useMutation({
    mutationFn: (smiles: string) => assessDruglikeness(smiles),
    onSuccess: (res) => {
      const data = (res as any)?.data || res;
      setAssessResult(data);
    },
  });

  const admetMutation = useMutation({
    mutationFn: (smiles: string) => predictProperties(smiles),
    onSuccess: (res) => {
      const data = (res as any)?.data || res;
      setAdmetResult(data);
    },
  });

  const explainMutation = useMutation({
    mutationFn: (smiles: string) => explainMolecule(smiles),
    onSuccess: (res) => {
      const data = (res as any)?.data || res;
      setExplainResult(data);
    },
  });

  const deleteMutation = useMutation({
    mutationFn: (id: string) => deleteMolecule(id),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['molecules'] });
      toast.success('删除成功', '分子已删除');
    },
    onError: (err: any) => {
      toast.error('删除失败', err?.response?.data?.error?.message || '无权删除或分子不存在');
    },
  });

  const multiTargetMutation = useMutation({
    mutationFn: (params: { targets: any[]; seedSmiles?: string; nMolecules?: number }) =>
      designMultiTargetMolecules(params.targets, params.seedSmiles, undefined, params.nMolecules),
    onSuccess: (data) => {
      setMultiTargetResult(data);
      toast.success('多靶点设计完成', `生成了 ${data?.designed_molecules?.length || 0} 个候选分子`);
    },
    onError: (err: any) => {
      toast.error('多靶点设计失败', err?.response?.data?.error?.message || '请稍后重试');
    },
  });

  // 自动设计：获取第一个靶点并自动设计分子
  const autoDesignMutation = useMutation({
    mutationFn: async () => {
      setAutoDesignProgress('正在获取靶点列表...');
      const targetsResp = await getTargets();
      const targetsList = (targetsResp as any)?.items || (Array.isArray(targetsResp) ? targetsResp : []);
      if (!targetsList || targetsList.length === 0) {
        throw new Error('没有可用的靶点，请先在「靶点发现」页面发现靶点');
      }
      const firstTarget = targetsList[0];
      setAutoDesignProgress(`正在基于靶点 ${firstTarget.gene_symbol} 设计分子...`);
      const result = await designMolecule({
        target_id: firstTarget.id,
        constraints: { mw_max: 500, logp_max: 5 },
      });
      return { result, geneSymbol: firstTarget.gene_symbol };
    },
    onSuccess: ({ result, geneSymbol }) => {
      setAutoDesignProgress('');
      queryClient.invalidateQueries({ queryKey: ['molecules'] });
      const designed = result?.designed_molecules || result?.data?.designed_molecules || [];
      toast.success('自动设计完成', `基于靶点 ${geneSymbol} 设计了 ${designed.length} 个候选分子`);
    },
    onError: (err: any) => {
      setAutoDesignProgress('');
      toast.error('自动设计失败', err?.message || '请稍后重试');
    },
  });

  // 详情打开时自动调用 ADMET 预测和分子解析
  useEffect(() => {
    if (!detail?.smiles) {
      setDetailAdmet(null);
      setDetailExplain(null);
      return;
    }
    setDetailAdmetLoading(true);
    setDetailExplainLoading(true);
    predictProperties(detail.smiles)
      .then((res: any) => setDetailAdmet(res?.data || res))
      .catch(() => setDetailAdmet(null))
      .finally(() => setDetailAdmetLoading(false));
    explainMolecule(detail.smiles)
      .then((res: any) => setDetailExplain(res?.data || res))
      .catch(() => setDetailExplain(null))
      .finally(() => setDetailExplainLoading(false));
  }, [detail]);

  // 自动匹配靶点生成药物列表
  const handleAutoMatch = async () => {
    if (!currentProject?.id) {
      toast.warning('未选择项目', '请先选择一个项目');
      return;
    }
    setAutoMatchLoading(true);
    setAutoMatchResult(null);
    try {
      const res: any = await optimizeTreatments(currentProject.id);
      setAutoMatchResult(res?.data || res);
      toast.success('匹配完成', '已根据分子与靶点自动生成药物/治疗方案列表');
    } catch (err: any) {
      toast.error('匹配失败', err?.response?.data?.error?.message || err?.message || '请稍后重试');
    } finally {
      setAutoMatchLoading(false);
    }
  };

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold">分子库</h1>
          <p className="text-sm text-gray-500 mt-1">已设计/已批准的候选分子 — SMILES、类药性、对接结果</p>
        </div>
        <div className="flex gap-2 flex-wrap">
          <Button variant="secondary" onClick={() => { setAssessResult(null); setShowAssess(true); }}>
            <Gauge className="w-4 h-4" /> 评估 SMILES
          </Button>
          <Button variant="secondary" onClick={() => { setAdmetResult(null); setShowAdmet(true); }}>
            <Microscope className="w-4 h-4" /> ADMET 预测
          </Button>
          <Button variant="secondary" onClick={() => { setExplainResult(null); setShowExplain(true); }}>
            <ScanSearch className="w-4 h-4" /> 分子解析
          </Button>
          <Button onClick={() => { setDesignResult(null); setShowDesign(true); }}>
            <Plus className="w-4 h-4" /> 设计分子
          </Button>
          <Button variant="primary" onClick={() => { setMultiTargetResult(null); setShowMultiTarget(true); }}>
            <TargetIcon className="w-4 h-4" /> 多靶点协同设计
          </Button>
          <Button
            variant="secondary"
            loading={autoMatchLoading}
            onClick={handleAutoMatch}
            disabled={!currentProject?.id}
          >
            <Link2 className="w-4 h-4" /> 自动匹配靶点生成药物列表
          </Button>
        </div>
      </div>

      {/* 自动设计区域 */}
      <Card title="一键自动设计">
        <div className="flex items-center gap-4">
          <Button
            variant="primary"
            loading={autoDesignMutation.isPending}
            onClick={() => autoDesignMutation.mutate()}
          >
            <Zap className="w-4 h-4" /> 自动设计药物分子
          </Button>
          {autoDesignProgress && (
            <span className="text-sm text-primary-600 animate-pulse">{autoDesignProgress}</span>
          )}
          <span className="text-xs text-gray-400">
            自动获取第一个靶点，基于 AI 模型生成候选分子
          </span>
        </div>
        {(autoDesignMutation.isPending || designMutation.isPending) && (
          <div className="mt-3">
            <ProgressBar
              status="running"
              percent={50}
              message={autoDesignMutation.isPending ? '正在自动设计分子...' : '正在设计分子...'}
            />
          </div>
        )}
      </Card>

      <Card title={`分子列表 (${molecules?.length || 0})`}>
        {isError ? (
          <div className="rounded-xl border border-red-200 bg-red-50 p-6 text-center">
            <p className="text-sm text-red-600 mb-3">数据加载失败</p>
            <button onClick={() => refetch()} className="text-xs text-primary-600 underline">重试</button>
          </div>
        ) : isLoading ? (
          <div className="text-center py-8 text-gray-400">加载中...</div>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b border-gray-200 text-gray-500">
                  <th className="text-left py-2 px-3">名称</th>
                  <th className="text-left py-2 px-3">SMILES</th>
                  <th className="text-left py-2 px-3">分子量</th>
                  <th className="text-left py-2 px-3">LogP</th>
                  <th className="text-left py-2 px-3">来源</th>
                  <th className="text-left py-2 px-3">操作</th>
                </tr>
              </thead>
              <tbody>
                {molecules?.map((m: any) => (
                  <tr key={m.id} className="border-b border-gray-100 hover:bg-gray-50">
                    <td className="py-2 px-3 font-medium">{m.name || '未命名'}</td>
                    <td className="py-2 px-3 font-mono text-xs text-gray-600 max-w-xs truncate">
                      {m.smiles}
                    </td>
                    <td className="py-2 px-3">{m.molecular_weight?.toFixed(1) || '—'}</td>
                    <td className="py-2 px-3">{m.logp?.toFixed(2) || '—'}</td>
                    <td className="py-2 px-3">
                      {m.is_approved ? (
                        <Badge variant="status" value="completed" />
                      ) : (
                        <Badge variant="status" value="planned" />
                      )}
                      <span className="ml-1 text-xs text-gray-500">{m.source || ''}</span>
                    </td>
                    <td className="py-2 px-3">
                      <div className="flex gap-1">
                        <Button size="sm" variant="ghost" onClick={() => setDetail(m)}>
                          详情
                        </Button>
                        <Button
                          size="sm"
                          variant="ghost"
                          loading={deleteMutation.isPending}
                          onClick={() => setDeleteTarget({ id: m.id, name: m.name || m.smiles.slice(0, 20) })}
                        >
                          <Trash2 className="w-3 h-3" /> 删除
                        </Button>
                      </div>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
            {(!molecules || molecules.length === 0) && (
              <div className="text-center py-8 text-gray-400">
                <Atom className="w-12 h-12 mx-auto mb-2 opacity-50" />
                暂无分子，点击「设计分子」或「评估 SMILES」开始
              </div>
            )}
          </div>
        )}
      </Card>

      {/* 详情抽屉 + 雷达图 */}
      {detail && (
        <div className="fixed inset-0 bg-black/50 flex items-center justify-center z-50 p-4">
          <div className="bg-white rounded-lg max-w-2xl w-full max-h-[80vh] overflow-y-auto">
            <div className="flex items-center justify-between px-5 py-3 border-b">
              <h3 className="font-semibold">分子详情 — {detail.name || '未命名'}</h3>
              <button onClick={() => setDetail(null)}>
                <X className="w-5 h-5 text-gray-400" />
              </button>
            </div>
            <div className="p-5 space-y-4">
              <div>
                <div className="text-sm text-gray-500 mb-1">SMILES</div>
                <div className="font-mono text-xs bg-gray-50 p-2 rounded break-all">{detail.smiles}</div>
              </div>
              <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
                <div className="bg-gray-50 p-3 rounded">
                  <div className="text-xs text-gray-500">分子量</div>
                  <div className="text-lg font-semibold">{detail.molecular_weight?.toFixed(1) || '—'}</div>
                </div>
                <div className="bg-gray-50 p-3 rounded">
                  <div className="text-xs text-gray-500">LogP</div>
                  <div className="text-lg font-semibold">{detail.logp?.toFixed(2) || '—'}</div>
                </div>
                <div className="bg-gray-50 p-3 rounded">
                  <div className="text-xs text-gray-500">InChI Key</div>
                  <div className="text-xs font-mono">{detail.inchi_key || '—'}</div>
                </div>
                <div className="bg-gray-50 p-3 rounded">
                  <div className="text-xs text-gray-500">ChEMBL ID</div>
                  <div className="text-xs font-mono">{detail.chembl_id || '—'}</div>
                </div>
              </div>

              {/* 类药性详细指标 */}
              {detail.properties && (
                <div className="bg-blue-50 border border-blue-100 rounded-lg p-4 space-y-2">
                  <h4 className="text-sm font-semibold text-blue-900">类药性评估详情</h4>
                  <div className="grid grid-cols-2 md:grid-cols-4 gap-2 text-xs">
                    <div><span className="text-gray-600">氢键供体 (HBD):</span> <span className="font-medium">{detail.properties.hbd ?? '—'}</span></div>
                    <div><span className="text-gray-600">氢键受体 (HBA):</span> <span className="font-medium">{detail.properties.hba ?? '—'}</span></div>
                    <div><span className="text-gray-600">可旋转键:</span> <span className="font-medium">{detail.properties.rotatable_bonds ?? '—'}</span></div>
                    <div><span className="text-gray-600">极性表面积 (TPSA):</span> <span className="font-medium">{detail.properties.tpsa ?? '—'}</span></div>
                    <div><span className="text-gray-600">环数:</span> <span className="font-medium">{detail.properties.n_rings ?? '—'}</span></div>
                    <div><span className="text-gray-600">芳香环数:</span> <span className="font-medium">{detail.properties.n_aromatic_rings ?? '—'}</span></div>
                    <div>
                      <span className="text-gray-600">Lipinski 五规则:</span>{' '}
                      <span className={`font-medium ${detail.properties.passes_rule_of_five ? 'text-green-700' : 'text-red-700'}`}>
                        {detail.properties.passes_rule_of_five ? '通过' : '违反'}
                      </span>
                    </div>
                    <div>
                      <span className="text-gray-600">Veber 规则:</span>{' '}
                      <span className={`font-medium ${detail.properties.passes_veber_rule ? 'text-green-700' : 'text-red-700'}`}>
                        {detail.properties.passes_veber_rule ? '通过' : '违反'}
                      </span>
                    </div>
                  </div>
                  {detail.properties.druglikeness_score != null && (
                    <div className="flex items-center gap-2 pt-2 border-t border-blue-100">
                      <span className="text-xs text-gray-600">类药性综合评分:</span>
                      <div className="flex-1 h-2 bg-blue-100 rounded-full overflow-hidden">
                        <div className="h-full bg-blue-600 rounded-full" style={{ width: `${detail.properties.druglikeness_score}%` }} />
                      </div>
                      <span className="text-sm font-bold text-blue-700">{detail.properties.druglikeness_score}/100</span>
                    </div>
                  )}
                  {detail.properties.violations?.length > 0 && (
                    <div className="pt-2 border-t border-blue-100">
                      <div className="text-xs text-gray-600 mb-1">违反规则:</div>
                      <ul className="text-xs text-red-600 list-disc list-inside">
                        {detail.properties.violations.map((v: string, i: number) => <li key={i}>{v}</li>)}
                      </ul>
                    </div>
                  )}
                </div>
              )}

              {/* 来源与设计信息 */}
              <div className="grid grid-cols-2 gap-3 text-sm">
                <div className="bg-gray-50 p-3 rounded">
                  <div className="text-xs text-gray-500">来源</div>
                  <div className="font-medium">{detail.source || '—'}</div>
                </div>
                <div className="bg-gray-50 p-3 rounded">
                  <div className="text-xs text-gray-500">设计方式</div>
                  <div className="font-medium">{detail.designed_by || '—'}</div>
                </div>
              </div>

              {/* 分子功能详细介绍 */}
              <MoleculeFunctionIntro detail={detail} />

              {/* ADMET 预测（自动调用 API） */}
              <div>
                <h4 className="text-sm font-semibold mb-2 flex items-center gap-2">
                  <Microscope className="w-4 h-4 text-purple-600" /> ADMET 预测
                  {detailAdmetLoading && <span className="text-xs text-gray-400 animate-pulse">加载中...</span>}
                </h4>
                {detailAdmet && !detailAdmet.error ? (
                  <div className="bg-purple-50 border border-purple-100 rounded-lg p-4 space-y-3">
                    {detailAdmet.summary && (
                      <div className="flex items-center gap-3 text-sm">
                        <span className={`px-3 py-1 rounded-lg font-medium border ${
                          detailAdmet.summary.toxicity === 'high' ? 'bg-red-100 text-red-700 border-red-200' :
                          detailAdmet.summary.toxicity === 'medium' ? 'bg-yellow-100 text-yellow-700 border-yellow-200' :
                          'bg-green-100 text-green-700 border-green-200'
                        }`}>
                          综合毒性: {detailAdmet.summary.toxicity?.toUpperCase()}
                        </span>
                        <span className="text-gray-600">风险计数: {detailAdmet.summary.risk_count}</span>
                      </div>
                    )}
                    <div className="grid grid-cols-2 md:grid-cols-4 gap-2 text-xs">
                      <div className="bg-white p-2 rounded"><span className="text-gray-500">LogS:</span> <span className="font-medium">{detailAdmet.logS ?? '—'}</span></div>
                      <div className="bg-white p-2 rounded"><span className="text-gray-500">生物利用度:</span> <span className="font-medium">{detailAdmet.bioavailability_score ?? '—'}</span></div>
                      <div className="bg-white p-2 rounded"><span className="text-gray-500">BBB 渗透:</span> <span className="font-medium">{detailAdmet.bbb_permeability ?? '—'}</span></div>
                      <div className="bg-white p-2 rounded"><span className="text-gray-500">Caco-2:</span> <span className="font-medium">{detailAdmet.caco2_permeability ?? '—'}</span></div>
                      <div className="bg-white p-2 rounded"><span className="text-gray-500">hERG 风险:</span> <span className="font-medium">{detailAdmet.herg_risk ?? '—'}</span></div>
                      <div className="bg-white p-2 rounded"><span className="text-gray-500">血浆蛋白结合:</span> <span className="font-medium">{detailAdmet.plasma_protein_binding ?? '—'}</span></div>
                      <div className="bg-white p-2 rounded"><span className="text-gray-500">PAINS 警告:</span> <span className="font-medium">{detailAdmet.pains_alerts?.length ?? 0}</span></div>
                      <div className="bg-white p-2 rounded"><span className="text-gray-500">毒性警示:</span> <span className="font-medium">{detailAdmet.toxicophore_alerts?.length ?? 0}</span></div>
                    </div>
                  </div>
                ) : (
                  <div className="text-xs text-gray-400 bg-gray-50 p-3 rounded">
                    {detailAdmet?.error || (detailAdmetLoading ? '正在预测...' : '暂无 ADMET 预测数据')}
                  </div>
                )}
              </div>

              {/* 分子解析（自动调用 API） */}
              <div>
                <h4 className="text-sm font-semibold mb-2 flex items-center gap-2">
                  <ScanSearch className="w-4 h-4 text-indigo-600" /> 分子解析
                  {detailExplainLoading && <span className="text-xs text-gray-400 animate-pulse">加载中...</span>}
                </h4>
                {detailExplain && !detailExplain.error ? (
                  <div className="bg-indigo-50 border border-indigo-100 rounded-lg p-4 space-y-3">
                    {detailExplain.rings && (
                      <div className="grid grid-cols-3 gap-2 text-xs">
                        <div className="bg-white p-2 rounded text-center">
                          <div className="text-gray-500">芳香环</div>
                          <div className="text-lg font-semibold text-purple-700">{detailExplain.rings.aromatic}</div>
                        </div>
                        <div className="bg-white p-2 rounded text-center">
                          <div className="text-gray-500">脂肪环</div>
                          <div className="text-lg font-semibold text-blue-700">{detailExplain.rings.aliphatic}</div>
                        </div>
                        <div className="bg-white p-2 rounded text-center">
                          <div className="text-gray-500">总环数</div>
                          <div className="text-lg font-semibold text-gray-900">{detailExplain.rings.total}</div>
                        </div>
                      </div>
                    )}
                    {detailExplain.stereochemistry && (
                      <div className="grid grid-cols-2 gap-2 text-xs">
                        <div className="bg-white p-2 rounded">
                          <span className="text-gray-500">手性中心数:</span>
                          <span className="font-medium ml-1">{detailExplain.stereochemistry.chiral_centers}</span>
                        </div>
                        <div className="bg-white p-2 rounded">
                          <span className="text-gray-500">立体键数:</span>
                          <span className="font-medium ml-1">{detailExplain.stereochemistry.stereo_bonds}</span>
                        </div>
                      </div>
                    )}
                    {detailExplain.functional_groups?.length > 0 && (
                      <div className="space-y-1">
                        <div className="text-xs font-semibold text-gray-700">功能团识别</div>
                        {detailExplain.functional_groups.map((fg: any, i: number) => (
                          <div key={i} className="flex items-center justify-between bg-white p-2 rounded text-xs">
                            <div>
                              <span className="font-medium">{fg.name}</span>
                              <span className="ml-2 font-mono text-gray-500">{fg.smarts}</span>
                            </div>
                            <span className="px-2 py-0.5 bg-blue-100 text-blue-700 rounded font-medium">×{fg.count}</span>
                          </div>
                        ))}
                      </div>
                    )}
                  </div>
                ) : (
                  <div className="text-xs text-gray-400 bg-gray-50 p-3 rounded">
                    {detailExplain?.error || (detailExplainLoading ? '正在解析...' : '暂无分子解析数据')}
                  </div>
                )}
              </div>

              {/* Lipinski 雷达图 */}
              {detail.properties && (
                <div>
                  <h4 className="text-sm font-semibold mb-2">Lipinski 五规则雷达图</h4>
                  <PlotlyChart
                    data={[
                      {
                        type: 'scatterpolar',
                        r: [
                          detail.molecular_weight || 0,
                          detail.logp || 0,
                          detail.properties.hbd || 0,
                          detail.properties.hba || 0,
                          detail.properties.tpsa || 0,
                          detail.molecular_weight || 0,
                        ],
                        theta: ['MW', 'LogP', 'HBD', 'HBA', 'TPSA', 'MW'],
                        fill: 'toself',
                        line: { color: '#2563eb' },
                      },
                    ]}
                    layout={{
                      polar: { radialaxis: { visible: true } },
                      margin: { t: 20, b: 20, l: 40, r: 40 },
                      height: 350,
                    }}
                  />
                </div>
              )}

              {detail.docking_result && (
                <div>
                  <h4 className="text-sm font-semibold mb-2">对接结果</h4>
                  <pre className="bg-gray-900 text-gray-100 p-3 rounded text-xs overflow-x-auto">
                    {JSON.stringify(detail.docking_result, null, 2)}
                  </pre>
                </div>
              )}
            </div>
          </div>
        </div>
      )}

      {/* 自动匹配靶点生成药物列表结果 */}
      {autoMatchResult && (
        <Card title="自动匹配结果 — 药物/治疗方案列表">
          {autoMatchResult.treatments?.length > 0 || autoMatchResult.data?.treatments?.length > 0 ? (
            <div className="overflow-x-auto">
              <table className="w-full text-sm">
                <thead>
                  <tr className="border-b border-gray-200 text-gray-500">
                    <th className="text-left py-2 px-3">方案名称</th>
                    <th className="text-left py-2 px-3">治疗类型</th>
                    <th className="text-left py-2 px-3">靶点</th>
                    <th className="text-left py-2 px-3">分子</th>
                    <th className="text-left py-2 px-3">疗效评分</th>
                    <th className="text-left py-2 px-3">风险评分</th>
                    <th className="text-left py-2 px-3">置信度</th>
                  </tr>
                </thead>
                <tbody>
                  {(autoMatchResult.treatments || autoMatchResult.data?.treatments || []).map((t: any, i: number) => (
                    <tr key={i} className="border-b border-gray-100 hover:bg-gray-50">
                      <td className="py-2 px-3 font-medium">{t.name || '—'}</td>
                      <td className="py-2 px-3">{t.therapy_type || '—'}</td>
                      <td className="py-2 px-3">{(t.target_ids || []).length} 个</td>
                      <td className="py-2 px-3">{(t.molecule_ids || []).length} 个</td>
                      <td className="py-2 px-3 text-emerald-700 font-semibold">{t.efficacy_score?.toFixed(2) || '—'}</td>
                      <td className="py-2 px-3 text-red-700 font-semibold">{t.risk_score?.toFixed(2) || '—'}</td>
                      <td className="py-2 px-3 text-blue-700 font-semibold">{t.confidence != null ? (t.confidence * 100).toFixed(0) + '%' : '—'}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          ) : (
            <div className="text-sm text-gray-500 bg-gray-50 p-3 rounded">
              {autoMatchResult.message || autoMatchResult.data?.message || '暂无匹配结果，请先确保已发现靶点并设计了分子'}
            </div>
          )}
        </Card>
      )}

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
                确认删除分子「<span className="font-medium">{deleteTarget.name}</span>」？此操作不可撤销。
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

      {/* 设计分子弹窗 */}
      {showDesign && (
        <DesignModal
          loading={designMutation.isPending}
          result={designResult}
          onClose={() => setShowDesign(false)}
          onSubmit={(payload) => designMutation.mutate(payload)}
        />
      )}

      {/* 评估 SMILES 弹窗 */}
      {showAssess && (
        <AssessModal
          loading={assessMutation.isPending}
          result={assessResult}
          onClose={() => setShowAssess(false)}
          onSubmit={(smiles) => assessMutation.mutate(smiles)}
        />
      )}

      {/* ADMET 预测弹窗 */}
      {showAdmet && (
        <AdmetModal
          loading={admetMutation.isPending}
          result={admetResult}
          onClose={() => setShowAdmet(false)}
          onSubmit={(smiles) => admetMutation.mutate(smiles)}
        />
      )}

      {/* 分子解析弹窗 */}
      {showExplain && (
        <ExplainModal
          loading={explainMutation.isPending}
          result={explainResult}
          onClose={() => setShowExplain(false)}
          onSubmit={(smiles) => explainMutation.mutate(smiles)}
        />
      )}

      {/* 多靶点协同设计弹窗 */}
      {showMultiTarget && (
        <MultiTargetModal
          loading={multiTargetMutation.isPending}
          result={multiTargetResult}
          onClose={() => setShowMultiTarget(false)}
          onSubmit={(params) => multiTargetMutation.mutate(params)}
        />
      )}
    </div>
  );
}

function DesignModal({
  loading,
  result,
  onClose,
  onSubmit,
}: {
  loading: boolean;
  result: any;
  onClose: () => void;
  onSubmit: (payload: any) => void;
}) {
  const [targetId, setTargetId] = useState('');
  const [smiles, setSmiles] = useState('');
  const [mwMax, setMwMax] = useState('500');
  const [logpMax, setLogpMax] = useState('5');

  const handleSubmit = () => {
    onSubmit({
      target_id: targetId || undefined,
      smiles: smiles || undefined,
      constraints: { mw_max: Number(mwMax), logp_max: Number(logpMax) },
    });
  };

  return (
    <div className="fixed inset-0 bg-black/50 flex items-center justify-center z-50 p-4">
      <div className="bg-white rounded-lg max-w-2xl w-full max-h-[85vh] overflow-y-auto">
        <div className="flex items-center justify-between px-5 py-3 border-b">
          <h3 className="font-semibold flex items-center gap-2">
            <FlaskConical className="w-4 h-4" /> 分子设计（P2 DeepChem 框架）
          </h3>
          <button onClick={onClose}>
            <X className="w-5 h-5 text-gray-400" />
          </button>
        </div>
        <div className="p-5 space-y-4">
          <div>
            <label className="text-sm text-gray-500">靶点 ID（可选）</label>
            <input
              className="w-full border border-gray-300 rounded px-3 py-2 mt-1 text-sm"
              placeholder="例如：96d78aa1-b4f2-4bbd-8d63-43431bca1941"
              value={targetId}
              onChange={(e) => setTargetId(e.target.value)}
            />
          </div>
          <div>
            <label className="text-sm text-gray-500">种子 SMILES（可选）</label>
            <input
              className="w-full border border-gray-300 rounded px-3 py-2 mt-1 font-mono text-sm"
              placeholder="例如：CCO 或 COC1=CC=C(C=C1)N"
              value={smiles}
              onChange={(e) => setSmiles(e.target.value)}
            />
          </div>
          <div className="grid grid-cols-2 gap-3">
            <div>
              <label className="text-sm text-gray-500">分子量上限</label>
              <input
                type="number"
                className="w-full border border-gray-300 rounded px-3 py-2 mt-1 text-sm"
                value={mwMax}
                onChange={(e) => setMwMax(e.target.value)}
              />
            </div>
            <div>
              <label className="text-sm text-gray-500">LogP 上限</label>
              <input
                type="number"
                className="w-full border border-gray-300 rounded px-3 py-2 mt-1 text-sm"
                value={logpMax}
                onChange={(e) => setLogpMax(e.target.value)}
              />
            </div>
          </div>
          <Button onClick={handleSubmit} loading={loading} className="w-full">
            开始设计
          </Button>

          {result && (
            <div className="mt-4 border-t pt-4">
              <h4 className="text-sm font-semibold mb-2">设计结果</h4>
              {result.designed_molecules?.length > 0 ? (
                <div className="space-y-2">
                  {result.designed_molecules.map((m: any, i: number) => (
                    <div key={i} className="bg-gray-50 p-3 rounded text-sm">
                      <div className="font-mono text-xs break-all">{m.smiles}</div>
                      {m.predicted_toxicity !== undefined && (
                        <div className="text-xs text-gray-500 mt-1">预测毒性: {m.predicted_toxicity.toFixed(3)}</div>
                      )}
                    </div>
                  ))}
                </div>
              ) : (
                <div className="bg-yellow-50 border border-yellow-200 p-3 rounded text-sm text-gray-700">
                  <div className="font-medium mb-1">{result.model_info?.status || 'framework_only'}</div>
                  <div className="text-xs">{result.model_info?.message || result.fallback_action}</div>
                  {result.model_info?.required_packages && (
                    <div className="text-xs mt-1">需安装: {result.model_info.required_packages.join(', ')}</div>
                  )}
                </div>
              )}
            </div>
          )}
        </div>
      </div>
    </div>
  );
}

function AssessModal({
  loading,
  result,
  onClose,
  onSubmit,
}: {
  loading: boolean;
  result: any;
  onClose: () => void;
  onSubmit: (smiles: string) => void;
}) {
  const [smiles, setSmiles] = useState('CCO');

  return (
    <div className="fixed inset-0 bg-black/50 flex items-center justify-center z-50 p-4">
      <div className="bg-white rounded-lg max-w-2xl w-full max-h-[85vh] overflow-y-auto">
        <div className="flex items-center justify-between px-5 py-3 border-b">
          <h3 className="font-semibold flex items-center gap-2">
            <Gauge className="w-4 h-4" /> 类药性评估（Lipinski 五规则）
          </h3>
          <button onClick={onClose}>
            <X className="w-5 h-5 text-gray-400" />
          </button>
        </div>
        <div className="p-5 space-y-4">
          <div>
            <label className="text-sm text-gray-500">输入 SMILES 字符串</label>
            <div className="flex gap-2 mt-1">
              <input
                className="flex-1 border border-gray-300 rounded px-3 py-2 font-mono text-sm"
                placeholder="例如：CCO"
                value={smiles}
                onChange={(e) => setSmiles(e.target.value)}
              />
              <Button onClick={() => onSubmit(smiles)} loading={loading}>
                评估
              </Button>
            </div>
            <div className="text-xs text-gray-400 mt-1">示例：CCO(乙醇)、CC(=O)Oc1ccccc1C(=O)O(阿司匹林)、CN1C=NC2=C1C(=O)N(C(=O)N2C)C(咖啡因)</div>
          </div>

          {result && !result.error && (
            <div className="border-t pt-4 space-y-4">
              {result._note && (
                <div className="bg-blue-50 border border-blue-200 p-2 rounded text-xs text-blue-700">{result._note}</div>
              )}
              <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
                <MetricCard label="分子量 (MW)" value={result.mw} max={500} />
                <MetricCard label="LogP" value={result.logp} max={5} />
                <MetricCard label="氢键供体 (HBD)" value={result.hbd} max={5} />
                <MetricCard label="氢键受体 (HBA)" value={result.hba} max={10} />
                <MetricCard label="可旋转键" value={result.rotatable_bonds} max={10} />
                <MetricCard label="极性表面积 (TPSA)" value={result.tpsa} max={140} />
                <MetricCard label="环数" value={result.n_rings} />
                <MetricCard label="芳香环数" value={result.n_aromatic_rings} />
              </div>

              <div className="flex items-center gap-4">
                <div className={`px-3 py-2 rounded-lg text-sm font-medium ${result.passes_rule_of_five ? 'bg-green-100 text-green-700' : 'bg-red-100 text-red-700'}`}>
                  Lipinski 五规则: {result.passes_rule_of_five ? '通过' : '违反'}
                </div>
                <div className={`px-3 py-2 rounded-lg text-sm font-medium ${result.passes_veber_rule ? 'bg-green-100 text-green-700' : 'bg-red-100 text-red-700'}`}>
                  Veber 规则: {result.passes_veber_rule ? '通过' : '违反'}
                </div>
                <div className="px-3 py-2 rounded-lg text-sm font-medium bg-blue-100 text-blue-700">
                  类药性评分: {result.druglikeness_score}/100
                </div>
              </div>

              {result.violations?.length > 0 && (
                <div>
                  <div className="text-sm font-semibold mb-1">违反规则</div>
                  <ul className="text-xs text-red-600 list-disc list-inside">
                    {result.violations.map((v: string, i: number) => <li key={i}>{v}</li>)}
                  </ul>
                </div>
              )}

              <div>
                <h4 className="text-sm font-semibold mb-2">分子属性雷达图</h4>
                <PlotlyChart
                  data={[
                    {
                      type: 'scatterpolar',
                      r: [
                        Math.min(result.mw || 0, 600),
                        result.logp || 0,
                        result.hbd || 0,
                        result.hba || 0,
                        Math.min(result.tpsa || 0, 160),
                        Math.min(result.mw || 0, 600),
                      ],
                      theta: ['MW', 'LogP', 'HBD', 'HBA', 'TPSA', 'MW'],
                      fill: 'toself',
                      line: { color: '#2563eb' },
                      name: '分子属性',
                    },
                    {
                      type: 'scatterpolar',
                      r: [500, 5, 5, 10, 140, 500],
                      theta: ['MW', 'LogP', 'HBD', 'HBA', 'TPSA', 'MW'],
                      fill: 'none',
                      line: { color: '#ef4444', dash: 'dash' },
                      name: 'Lipinski 上限',
                    },
                  ]}
                  layout={{
                    polar: { radialaxis: { visible: true } },
                    margin: { t: 20, b: 20, l: 40, r: 40 },
                    height: 350,
                  }}
                />
              </div>
            </div>
          )}

          {result?.error && (
            <div className="bg-red-50 border border-red-200 p-3 rounded text-sm text-red-700">{result.error}</div>
          )}
        </div>
      </div>
    </div>
  );
}

function MetricCard({ label, value, max }: { label: string; value: any; max?: number }) {
  const numValue = Number(value) || 0;
  const overLimit = max !== undefined && numValue > max;
  return (
    <div className={`p-3 rounded ${overLimit ? 'bg-red-50 border border-red-200' : 'bg-gray-50'}`}>
      <div className="text-xs text-gray-500">{label}</div>
      <div className={`text-lg font-semibold ${overLimit ? 'text-red-600' : 'text-gray-900'}`}>
        {value ?? '—'}{max !== undefined && <span className="text-xs text-gray-400"> / {max}</span>}
      </div>
    </div>
  );
}

function AdmetModal({
  loading,
  result,
  onClose,
  onSubmit,
}: {
  loading: boolean;
  result: any;
  onClose: () => void;
  onSubmit: (smiles: string) => void;
}) {
  const [smiles, setSmiles] = useState('CCO');

  const levelColor = (level: string) => {
    if (level === 'high') return 'bg-red-100 text-red-700';
    if (level === 'medium') return 'bg-yellow-100 text-yellow-700';
    return 'bg-green-100 text-green-700';
  };

  const toxicityColor = (level: string) => {
    if (level === 'high') return 'bg-red-100 text-red-700 border-red-200';
    if (level === 'medium') return 'bg-yellow-100 text-yellow-700 border-yellow-200';
    return 'bg-green-100 text-green-700 border-green-200';
  };

  return (
    <div className="fixed inset-0 bg-black/50 flex items-center justify-center z-50 p-4">
      <div className="bg-white rounded-lg max-w-2xl w-full max-h-[85vh] overflow-y-auto">
        <div className="flex items-center justify-between px-5 py-3 border-b">
          <h3 className="font-semibold flex items-center gap-2">
            <Microscope className="w-4 h-4" /> ADMET 性质预测（RDKit）
          </h3>
          <button onClick={onClose}>
            <X className="w-5 h-5 text-gray-400" />
          </button>
        </div>
        <div className="p-5 space-y-4">
          <div>
            <label className="text-sm text-gray-500">输入 SMILES 字符串</label>
            <div className="flex gap-2 mt-1">
              <input
                className="flex-1 border border-gray-300 rounded px-3 py-2 font-mono text-sm"
                placeholder="例如：CCO"
                value={smiles}
                onChange={(e) => setSmiles(e.target.value)}
              />
              <Button onClick={() => onSubmit(smiles)} loading={loading}>
                预测
              </Button>
            </div>
            <div className="text-xs text-gray-400 mt-1">示例：CCO(乙醇)、CC(=O)Oc1ccccc1C(=O)O(阿司匹林)、CN1C=NC2=C1C(=O)N(C(=O)N2C)C(咖啡因)</div>
          </div>

          {result && !result.error && (
            <div className="border-t pt-4 space-y-4">
              {result._note && (
                <div className="bg-blue-50 border border-blue-200 p-2 rounded text-xs text-blue-700">{result._note}</div>
              )}

              {result.summary && (
                <div className="flex items-center gap-3">
                  <div className={`px-4 py-2 rounded-lg text-sm font-medium border ${toxicityColor(result.summary.toxicity)}`}>
                    综合毒性: {result.summary.toxicity?.toUpperCase()}
                  </div>
                  <div className="text-sm text-gray-600">
                    风险计数: {result.summary.risk_count}
                  </div>
                </div>
              )}

              <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
                <MetricCard label="LogS (溶解度)" value={result.logS} />
                <MetricCard label="生物利用度" value={result.bioavailability_score} />
                <div className="bg-gray-50 p-3 rounded">
                  <div className="text-xs text-gray-500">BBB 渗透性</div>
                  <div className={`mt-1 inline-block px-2 py-0.5 rounded text-xs font-medium ${levelColor(result.bbb_permeability)}`}>
                    {result.bbb_permeability}
                  </div>
                </div>
                <div className="bg-gray-50 p-3 rounded">
                  <div className="text-xs text-gray-500">Caco-2 渗透性</div>
                  <div className={`mt-1 inline-block px-2 py-0.5 rounded text-xs font-medium ${levelColor(result.caco2_permeability)}`}>
                    {result.caco2_permeability}
                  </div>
                </div>
                <div className="bg-gray-50 p-3 rounded">
                  <div className="text-xs text-gray-500">hERG 风险</div>
                  <div className={`mt-1 inline-block px-2 py-0.5 rounded text-xs font-medium ${levelColor(result.herg_risk)}`}>
                    {result.herg_risk}
                  </div>
                </div>
                <div className="bg-gray-50 p-3 rounded">
                  <div className="text-xs text-gray-500">血浆蛋白结合</div>
                  <div className={`mt-1 inline-block px-2 py-0.5 rounded text-xs font-medium ${levelColor(result.plasma_protein_binding)}`}>
                    {result.plasma_protein_binding}
                  </div>
                </div>
                <div className={`p-3 rounded ${result.pains_alerts?.length > 0 ? 'bg-yellow-50 border border-yellow-200' : 'bg-green-50'}`}>
                  <div className="text-xs text-gray-500">PAINS 警告</div>
                  <div className={`text-lg font-semibold ${result.pains_alerts?.length > 0 ? 'text-yellow-700' : 'text-green-700'}`}>
                    {result.pains_alerts?.length || 0}
                  </div>
                </div>
                <div className={`p-3 rounded ${result.toxicophore_alerts?.length > 0 ? 'bg-red-50 border border-red-200' : 'bg-green-50'}`}>
                  <div className="text-xs text-gray-500">毒性警示</div>
                  <div className={`text-lg font-semibold ${result.toxicophore_alerts?.length > 0 ? 'text-red-700' : 'text-green-700'}`}>
                    {result.toxicophore_alerts?.length || 0}
                  </div>
                </div>
              </div>

              {result.pains_alerts?.length > 0 && (
                <div>
                  <h4 className="text-sm font-semibold mb-2 text-yellow-700">PAINS 警告结构</h4>
                  <div className="space-y-1">
                    {result.pains_alerts.map((a: any, i: number) => (
                      <div key={i} className="bg-yellow-50 border border-yellow-200 p-2 rounded text-xs">
                        <span className="font-medium">{a.name}</span>
                        <span className="ml-2 font-mono text-gray-500">{a.smarts}</span>
                      </div>
                    ))}
                  </div>
                </div>
              )}

              {result.toxicophore_alerts?.length > 0 && (
                <div>
                  <h4 className="text-sm font-semibold mb-2 text-red-700">毒性警示结构</h4>
                  <div className="space-y-1">
                    {result.toxicophore_alerts.map((a: any, i: number) => (
                      <div key={i} className="bg-red-50 border border-red-200 p-2 rounded text-xs">
                        <span className="font-medium">{a.name}</span>
                        <span className="ml-2 font-mono text-gray-500">{a.smarts}</span>
                      </div>
                    ))}
                  </div>
                </div>
              )}
            </div>
          )}

          {result?.error && (
            <div className="bg-red-50 border border-red-200 p-3 rounded text-sm text-red-700">{result.error}</div>
          )}
        </div>
      </div>
    </div>
  );
}

function ExplainModal({
  loading,
  result,
  onClose,
  onSubmit,
}: {
  loading: boolean;
  result: any;
  onClose: () => void;
  onSubmit: (smiles: string) => void;
}) {
  const [smiles, setSmiles] = useState('CCO');

  return (
    <div className="fixed inset-0 bg-black/50 flex items-center justify-center z-50 p-4">
      <div className="bg-white rounded-lg max-w-2xl w-full max-h-[85vh] overflow-y-auto">
        <div className="flex items-center justify-between px-5 py-3 border-b">
          <h3 className="font-semibold flex items-center gap-2">
            <ScanSearch className="w-4 h-4" /> 分子结构解析（RDKit SMARTS）
          </h3>
          <button onClick={onClose}>
            <X className="w-5 h-5 text-gray-400" />
          </button>
        </div>
        <div className="p-5 space-y-4">
          <div>
            <label className="text-sm text-gray-500">输入 SMILES 字符串</label>
            <div className="flex gap-2 mt-1">
              <input
                className="flex-1 border border-gray-300 rounded px-3 py-2 font-mono text-sm"
                placeholder="例如：CCO"
                value={smiles}
                onChange={(e) => setSmiles(e.target.value)}
              />
              <Button onClick={() => onSubmit(smiles)} loading={loading}>
                解析
              </Button>
            </div>
            <div className="text-xs text-gray-400 mt-1">示例：CCO(乙醇)、CC(=O)Oc1ccccc1C(=O)O(阿司匹林)、C[C@H](N)C(=O)O(L-丙氨酸)</div>
          </div>

          {result && !result.error && (
            <div className="border-t pt-4 space-y-4">
              {result._note && (
                <div className="bg-blue-50 border border-blue-200 p-2 rounded text-xs text-blue-700">{result._note}</div>
              )}

              {result.rings && (
                <div className="grid grid-cols-3 gap-3">
                  <div className="bg-gray-50 p-3 rounded">
                    <div className="text-xs text-gray-500">芳香环</div>
                    <div className="text-lg font-semibold text-purple-700">{result.rings.aromatic}</div>
                  </div>
                  <div className="bg-gray-50 p-3 rounded">
                    <div className="text-xs text-gray-500">脂肪环</div>
                    <div className="text-lg font-semibold text-blue-700">{result.rings.aliphatic}</div>
                  </div>
                  <div className="bg-gray-50 p-3 rounded">
                    <div className="text-xs text-gray-500">总环数</div>
                    <div className="text-lg font-semibold text-gray-900">{result.rings.total}</div>
                  </div>
                </div>
              )}

              {result.stereochemistry && (
                <div className="grid grid-cols-2 gap-3">
                  <div className="bg-gray-50 p-3 rounded">
                    <div className="text-xs text-gray-500">手性中心数</div>
                    <div className={`text-lg font-semibold ${result.stereochemistry.chiral_centers > 0 ? 'text-orange-600' : 'text-gray-900'}`}>
                      {result.stereochemistry.chiral_centers}
                    </div>
                  </div>
                  <div className="bg-gray-50 p-3 rounded">
                    <div className="text-xs text-gray-500">立体键数</div>
                    <div className={`text-lg font-semibold ${result.stereochemistry.stereo_bonds > 0 ? 'text-orange-600' : 'text-gray-900'}`}>
                      {result.stereochemistry.stereo_bonds}
                    </div>
                  </div>
                </div>
              )}

              {result.functional_groups?.length > 0 && (
                <div>
                  <h4 className="text-sm font-semibold mb-2">功能团识别</h4>
                  <div className="space-y-1">
                    {result.functional_groups.map((fg: any, i: number) => (
                      <div key={i} className="flex items-center justify-between bg-gray-50 p-2 rounded text-xs">
                        <div className="flex-1">
                          <span className="font-medium text-gray-900">{fg.name}</span>
                          <span className="ml-2 font-mono text-gray-500">{fg.smarts}</span>
                        </div>
                        <span className="ml-2 px-2 py-0.5 bg-blue-100 text-blue-700 rounded font-medium">×{fg.count}</span>
                      </div>
                    ))}
                  </div>
                </div>
              )}

              {result.atom_counts && Object.keys(result.atom_counts).length > 0 && (
                <div>
                  <h4 className="text-sm font-semibold mb-2">原子组成</h4>
                  <div className="flex flex-wrap gap-2">
                    {Object.entries(result.atom_counts).map(([symbol, count]: [string, any]) => (
                      <div key={symbol} className="bg-indigo-50 border border-indigo-200 px-3 py-1 rounded text-xs">
                        <span className="font-mono font-medium text-indigo-700">{symbol}</span>
                        <span className="ml-1 text-gray-600">×{count}</span>
                      </div>
                    ))}
                  </div>
                </div>
              )}
            </div>
          )}

          {result?.error && (
            <div className="bg-red-50 border border-red-200 p-3 rounded text-sm text-red-700">{result.error}</div>
          )}
        </div>
      </div>
    </div>
  );
}

// ========== 分子功能介绍组件 ==========
function MoleculeFunctionIntro({ detail }: { detail: any }) {
  const intro = generateMoleculeIntro(detail);

  return (
    <div className="space-y-4">
      {/* 作用机制 */}
      <div className="bg-indigo-50 border border-indigo-200 rounded-lg p-4">
        <h4 className="font-semibold text-indigo-900 mb-2 flex items-center gap-2">
          <BookOpen className="w-4 h-4" /> 作用机制
        </h4>
        <p className="text-sm text-gray-700">{intro.mechanism}</p>
      </div>

      {/* 药理学分类 */}
      <div>
        <h4 className="font-semibold mb-2">药理学分类</h4>
        <div className="grid grid-cols-2 gap-3">
          <div className="bg-gray-50 p-3 rounded">
            <div className="text-xs text-gray-500">药物类别</div>
            <div className="text-sm font-medium">{intro.drugClass}</div>
          </div>
          <div className="bg-gray-50 p-3 rounded">
            <div className="text-xs text-gray-500">给药途径</div>
            <div className="text-sm font-medium">{intro.administration}</div>
          </div>
          <div className="bg-gray-50 p-3 rounded">
            <div className="text-xs text-gray-500">分子类型</div>
            <div className="text-sm font-medium">{intro.moleculeType}</div>
          </div>
          <div className="bg-gray-50 p-3 rounded">
            <div className="text-xs text-gray-500">成药性评估</div>
            <div className="text-sm font-medium">{intro.druglikeness}</div>
          </div>
        </div>
      </div>

      {/* 结构特征 */}
      <div>
        <h4 className="font-semibold mb-2">结构特征分析</h4>
        <div className="bg-gray-50 rounded-lg p-4 text-sm text-gray-700 space-y-2">
          {intro.structuralFeatures.map((s: string, i: number) => (
            <div key={i} className="flex items-start gap-2">
              <span className="text-indigo-600 font-bold shrink-0">•</span>
              <span>{s}</span>
            </div>
          ))}
        </div>
      </div>

      {/* ADMET 概要 */}
      <div>
        <h4 className="font-semibold mb-2">ADMET 概要</h4>
        <div className="grid grid-cols-2 md:grid-cols-3 gap-3">
          {intro.admet.map((a: any, i: number) => (
            <div key={i} className={`p-3 rounded border ${a.pass ? 'bg-green-50 border-green-200' : 'bg-yellow-50 border-yellow-200'}`}>
              <div className="text-xs text-gray-500">{a.name}</div>
              <div className="text-sm font-medium text-gray-900">{a.value}</div>
              <div className="text-xs text-gray-500 mt-1">{a.note}</div>
            </div>
          ))}
        </div>
      </div>

      {/* 临床应用前景 */}
      <div className="bg-green-50 border border-green-200 rounded-lg p-4">
        <h4 className="font-semibold text-green-900 mb-2">临床应用前景</h4>
        <ul className="space-y-2">
          {intro.clinicalApplications.map((c: string, i: number) => (
            <li key={i} className="text-sm text-gray-700 flex items-start gap-2">
              <span className="text-green-600 font-bold shrink-0">→</span>
              <span>{c}</span>
            </li>
          ))}
        </ul>
      </div>

      {/* 安全性提示 */}
      <div className="bg-amber-50 border border-amber-200 rounded-lg p-4">
        <h4 className="font-semibold text-amber-900 mb-2">安全性提示</h4>
        <ul className="space-y-2">
          {intro.safetyNotes.map((s: string, i: number) => (
            <li key={i} className="text-sm text-gray-700 flex items-start gap-2">
              <span className="text-amber-600 font-bold shrink-0">⚠</span>
              <span>{s}</span>
            </li>
          ))}
        </ul>
      </div>
    </div>
  );
}

// 分子功能介绍生成器
function generateMoleculeIntro(detail: any) {
  const mw = detail.molecular_weight || 0;
  const logp = detail.logp || 0;
  const props = detail.properties || {};
  const hbd = props.hbd || 0;
  const hba = props.hba || 0;
  const tpsa = props.tpsa || 0;
  const rings = props.n_rings || 0;
  const aromaticRings = props.n_aromatic_rings || 0;
  const rotatableBonds = props.rotatable_bonds || 0;
  const passesLipinski = props.passes_rule_of_five;
  const passesVeber = props.passes_veber_rule;
  const score = props.druglikeness_score || 0;
  const isApproved = detail.is_approved;

  // 药物类别判断
  let drugClass = '小分子化合物';
  if (mw > 900) drugClass = '大分子/多肽类药物';
  else if (mw < 300) drugClass = '片段分子（Fragment）';
  else if (aromaticRings >= 3) drugClass = '芳香族杂环化合物';
  else if (rings > 0 && aromaticRings === 0) drugClass = '脂环类化合物';

  // 分子类型
  let moleculeType = '候选化合物';
  if (isApproved) moleculeType = '已获批药物';
  else if (score >= 80) moleculeType = '高成药性候选分子';
  else if (score >= 60) moleculeType = '中等成药性候选分子';
  else moleculeType = '需优化的先导化合物';

  // 给药途径预测
  let administration = '口服（推测）';
  if (tpsa > 140) administration = '注射给药（口服生物利用度低）';
  else if (mw > 500 && logp > 5) administration = '注射或局部给药';
  else if (rotatableBonds <= 10 && tpsa <= 140) administration = '口服（预测良好）';

  // 成药性评估
  let druglikeness = `${score}/100`;
  if (score >= 80) druglikeness += '（优秀）';
  else if (score >= 60) druglikeness += '（良好）';
  else if (score >= 40) druglikeness += '（一般）';
  else druglikeness += '（需优化）';

  // 作用机制
  let mechanism = `该分子分子量为 ${mw.toFixed(1)} Da，LogP 为 ${logp.toFixed(2)}，`;
  if (aromaticRings > 0) {
    mechanism += `含有 ${aromaticRings} 个芳香环，通常能与蛋白靶点形成 π-π 堆积相互作用，增强靶点亲和力。`;
  }
  if (hbd > 0 || hba > 0) {
    mechanism += `分子含有 ${hbd} 个氢键供体和 ${hba} 个氢键受体，能够与靶蛋白活性位点形成氢键网络，是分子识别的关键。`;
  }
  if (rotatableBonds > 5) {
    mechanism += `可旋转键较多（${rotatableBonds} 个），分子柔性较大，可能影响结合选择性，建议进行构象约束优化。`;
  } else {
    mechanism += `可旋转键较少（${rotatableBonds} 个），分子刚性较好，有利于选择性结合。`;
  }
  if (passesLipinski && passesVeber) {
    mechanism += '该分子符合 Lipinski 五规则和 Veber 规则，具有良好的口服成药性。';
  } else if (passesLipinski) {
    mechanism += '该分子符合 Lipinski 五规则但违反 Veber 规则，口服吸收可能受限。';
  } else {
    mechanism += '该分子违反 Lipinski 五规则，成药性存在风险，需要结构优化。';
  }

  // 结构特征
  const structuralFeatures: string[] = [];
  structuralFeatures.push(`分子量 ${mw.toFixed(1)} Da ${mw <= 500 ? '（符合 Lipinski 规则 ≤500）' : '（超出 Lipinski 建议 ≤500）'}`);
  structuralFeatures.push(`脂水分配系数 LogP = ${logp.toFixed(2)} ${logp <= 5 ? '（亲脂性适中，透膜性好）' : '（亲脂性过强，溶解度可能不足）'}`);
  structuralFeatures.push(`极性表面积 TPSA = ${tpsa.toFixed(1)} Å² ${tpsa <= 140 ? '（有利于口服吸收）' : '（口服生物利用度可能降低）'}`);
  if (rings > 0) {
    structuralFeatures.push(`含 ${rings} 个环（其中 ${aromaticRings} 个芳香环），环状结构有助于提高分子刚性和靶点亲和力`);
  }
  if (rotatableBonds > 0) {
    structuralFeatures.push(`含 ${rotatableBonds} 个可旋转键，${rotatableBonds <= 10 ? '分子柔性适中' : '柔性过大，影响选择性'}`);
  }

  // ADMET 概要
  const admet: any[] = [];
  admet.push({
    name: '口服吸收',
    value: tpsa <= 140 && mw <= 500 ? '良好' : '一般',
    pass: tpsa <= 140 && mw <= 500,
    note: tpsa <= 140 ? 'TPSA 符合要求' : 'TPSA 偏高',
  });
  admet.push({
    name: '血脑屏障',
    value: logp > 0 && logp < 5 && tpsa < 90 ? '可渗透' : '不易渗透',
    pass: logp > 0 && logp < 5 && tpsa < 90,
    note: tpsa < 90 ? '适合中枢神经药物' : '中枢神经渗透性低',
  });
  admet.push({
    name: '代谢稳定性',
    value: aromaticRings > 0 && aromaticRings <= 3 ? '适中' : '需评估',
    pass: aromaticRings > 0 && aromaticRings <= 3,
    note: '芳香环数影响 CYP 代谢',
  });
  admet.push({
    name: '心脏毒性',
    value: hba <= 10 ? '低风险' : '需关注',
    pass: hba <= 10,
    note: 'hERG 通道风险需进一步验证',
  });
  admet.push({
    name: '溶解度',
    value: logp < 3 ? '良好' : logp < 5 ? '适中' : '较差',
    pass: logp < 5,
    note: logp < 3 ? '水溶性好' : '亲脂性强，溶解度低',
  });
  admet.push({
    name: '类药性',
    value: passesLipinski ? '通过' : '未通过',
    pass: passesLipinski,
    note: 'Lipinski 五规则评估',
  });

  // 临床应用前景
  const clinicalApplications: string[] = [];
  if (isApproved) {
    clinicalApplications.push('该分子已获批上市，具有明确的临床应用价值。');
  } else {
    clinicalApplications.push(`该候选分子成药性评分 ${score}/100，${score >= 70 ? '具备进一步开发价值，建议推进临床前研究。' : '需要结构优化以提高成药性。'}`);
  }
  if (passesLipinski && tpsa <= 140) {
    clinicalApplications.push('符合口服药物标准，适合开发为口服固体制剂，患者依从性高。');
  } else if (tpsa > 140) {
    clinicalApplications.push('口服生物利用度受限，建议开发为注射剂型或进行前药设计。');
  }
  if (logp > 0 && logp < 5 && tpsa < 90) {
    clinicalApplications.push('理化性质适合中枢神经系统药物开发，可探索脑肿瘤适应症。');
  }
  clinicalApplications.push('建议进行体外活性测试（酶抑制/细胞毒性）和体内药效学评估，验证药理活性。');
  if (aromaticRings > 0 && aromaticRings <= 3) {
    clinicalApplications.push('芳香环结构适中，与已知药物数据库比对可发现潜在的老药新用机会。');
  }

  // 安全性提示
  const safetyNotes: string[] = [];
  if (!passesLipinski) {
    safetyNotes.push('分子违反 Lipinski 五规则，可能存在吸收、分布问题，需关注药代动力学参数。');
  }
  if (logp > 5) {
    safetyNotes.push('LogP 偏高，脂溶性强，可能在体内蓄积，需监测肝脏毒性。');
  }
  if (tpsa > 140) {
    safetyNotes.push('极性表面积偏大，影响口服吸收，建议评估生物利用度。');
  }
  if (rotatableBonds > 10) {
    safetyNotes.push('可旋转键过多，分子柔性大，可能影响代谢稳定性和选择性。');
  }
  if (props.violations?.length > 0) {
    safetyNotes.push(`违反 ${props.violations.length} 条类药性规则：${props.violations.join('、')}。`);
  }
  if (safetyNotes.length === 0) {
    safetyNotes.push('未发现明显安全性风险，但仍需进行完整的毒理学评估。');
    safetyNotes.push('建议进行 hERG 心脏毒性测试、Ames 致突变试验和肝毒性评估。');
  }

  return {
    mechanism,
    drugClass,
    administration,
    moleculeType,
    druglikeness,
    structuralFeatures,
    admet,
    clinicalApplications,
    safetyNotes,
  };
}

// ========== 多靶点协同分子设计组件 ==========
function MultiTargetModal({
  loading,
  result,
  onClose,
  onSubmit,
}: {
  loading: boolean;
  result: any;
  onClose: () => void;
  onSubmit: (params: { targets: any[]; seedSmiles?: string; nMolecules?: number }) => void;
}) {
  const [targets, setTargets] = useState<any[]>([
    { target_id: '', name: '', binding_site: '', weight: 1.0 },
  ]);
  const [seedSmiles, setSeedSmiles] = useState('');
  const [nMolecules, setNMolecules] = useState(10);

  // 自动加载已发现的靶点列表
  const { data: existingTargets } = useQuery({
    queryKey: ['targets-for-multi-design'],
    queryFn: () => getTargets(),
  });

  useEffect(() => {
    if (existingTargets) {
      const list = Array.isArray(existingTargets)
        ? existingTargets
        : (existingTargets as any)?.items || [];
      if (list.length > 0) {
        const autoTargets = list.slice(0, 5).map((t: any) => ({
          target_id: t.id || t.target_id || '',
          name: t.gene_symbol || t.name || '',
          binding_site: '',
          weight: 1.0,
        }));
        setTargets(autoTargets);
      }
    }
  }, [existingTargets]);

  const addTarget = () => {
    setTargets([...targets, { target_id: '', name: '', binding_site: '', weight: 1.0 }]);
  };

  const removeTarget = (index: number) => {
    if (targets.length > 1) {
      setTargets(targets.filter((_, i) => i !== index));
    }
  };

  const updateTarget = (index: number, field: string, value: any) => {
    const updated = [...targets];
    updated[index] = { ...updated[index], [field]: value };
    setTargets(updated);
  };

  const handleSubmit = () => {
    const validTargets = targets.filter((t) => t.target_id.trim());
    if (validTargets.length === 0) {
      return;
    }
    onSubmit({
      targets: validTargets,
      seedSmiles: seedSmiles || undefined,
      nMolecules,
    });
  };

  const designedMolecules = result?.designed_molecules || [];

  return (
    <div className="fixed inset-0 bg-black/50 flex items-center justify-center z-50 p-4">
      <div className="bg-white rounded-lg max-w-6xl w-full max-h-[90vh] overflow-y-auto">
        <div className="flex items-center justify-between px-5 py-3 border-b sticky top-0 bg-white z-10">
          <h3 className="font-semibold flex items-center gap-2">
            <TargetIcon className="w-5 h-5 text-primary-600" /> 多靶点协同分子设计
          </h3>
          <button onClick={onClose}>
            <X className="w-5 h-5 text-gray-400" />
          </button>
        </div>

        <div className="p-5 space-y-4">
          {/* 靶点列表 */}
          <Card title={`靶点列表 (${targets.length})`}>
            <div className="space-y-2">
              {targets.map((t, i) => (
                <div key={i} className="grid grid-cols-12 gap-2 items-center">
                  <input
                    className="col-span-3 border border-gray-300 rounded px-2 py-1 text-sm"
                    placeholder="靶点 ID"
                    value={t.target_id}
                    onChange={(e) => updateTarget(i, 'target_id', e.target.value)}
                  />
                  <input
                    className="col-span-3 border border-gray-300 rounded px-2 py-1 text-sm"
                    placeholder="靶点名称"
                    value={t.name}
                    onChange={(e) => updateTarget(i, 'name', e.target.value)}
                  />
                  <input
                    className="col-span-3 border border-gray-300 rounded px-2 py-1 text-sm"
                    placeholder="结合位点（片段）"
                    value={t.binding_site}
                    onChange={(e) => updateTarget(i, 'binding_site', e.target.value)}
                  />
                  <input
                    type="number"
                    step="0.1"
                    className="col-span-2 border border-gray-300 rounded px-2 py-1 text-sm"
                    placeholder="权重"
                    value={t.weight}
                    onChange={(e) => updateTarget(i, 'weight', parseFloat(e.target.value) || 1.0)}
                  />
                  <button
                    onClick={() => removeTarget(i)}
                    className="col-span-1 text-red-500 hover:text-red-700 text-sm"
                    disabled={targets.length === 1}
                  >
                    <Trash2 className="w-4 h-4" />
                  </button>
                </div>
              ))}
            </div>
            <div className="mt-2">
              <Button size="sm" variant="ghost" onClick={addTarget}>
                <Plus className="w-3 h-3" /> 添加靶点
              </Button>
            </div>
          </Card>

          {/* 设计参数 */}
          <Card title="设计参数">
            <div className="grid grid-cols-2 gap-3">
              <div>
                <label className="block text-xs text-gray-600 mb-1">种子 SMILES（可选）</label>
                <input
                  type="text"
                  className="w-full border border-gray-300 rounded px-2 py-1 text-sm font-mono"
                  placeholder="例如：CCO"
                  value={seedSmiles}
                  onChange={(e) => setSeedSmiles(e.target.value)}
                />
              </div>
              <div>
                <label className="block text-xs text-gray-600 mb-1">生成分子数量</label>
                <input
                  type="number"
                  min="1"
                  max="50"
                  className="w-full border border-gray-300 rounded px-2 py-1 text-sm"
                  value={nMolecules}
                  onChange={(e) => setNMolecules(parseInt(e.target.value) || 10)}
                />
              </div>
            </div>
            <div className="mt-3">
              <Button onClick={handleSubmit} loading={loading}>
                <Zap className="w-4 h-4" /> 开始多靶点协同设计
              </Button>
            </div>
          </Card>

          {/* 结果展示 */}
          {result && (
            <Card title={`设计结果 (${designedMolecules.length} 个分子)`}>
              {result.model_info && (
                <div className="bg-blue-50 border border-blue-200 rounded-lg p-3 mb-3 text-sm text-blue-700">
                  {result.model_info.message}
                </div>
              )}

              {designedMolecules.length > 0 ? (
                <div className="overflow-x-auto">
                  <table className="w-full text-sm">
                    <thead>
                      <tr className="border-b border-gray-200 text-gray-500">
                        <th className="text-left py-2 px-2">SMILES</th>
                        <th className="text-left py-2 px-2">分子量</th>
                        <th className="text-left py-2 px-2">LogP</th>
                        <th className="text-left py-2 px-2">HBD</th>
                        <th className="text-left py-2 px-2">HBA</th>
                        <th className="text-left py-2 px-2">各靶点亲和力</th>
                        <th className="text-left py-2 px-2">综合评分</th>
                        <th className="text-left py-2 px-2">类药性</th>
                      </tr>
                    </thead>
                    <tbody>
                      {designedMolecules.map((m: any, i: number) => (
                        <tr key={i} className="border-b border-gray-100 hover:bg-gray-50">
                          <td className="py-2 px-2 font-mono text-xs max-w-xs truncate" title={m.smiles}>
                            {m.smiles}
                          </td>
                          <td className="py-2 px-2">{m.properties?.mw?.toFixed(1) || '—'}</td>
                          <td className="py-2 px-2">{m.properties?.logp?.toFixed(2) || '—'}</td>
                          <td className="py-2 px-2">{m.properties?.hbd ?? '—'}</td>
                          <td className="py-2 px-2">{m.properties?.hba ?? '—'}</td>
                          <td className="py-2 px-2">
                            <div className="flex flex-wrap gap-1">
                              {Object.entries(m.target_affinities || {}).map(([tid, ta]: [string, any]) => (
                                <span
                                  key={tid}
                                  className="px-1.5 py-0.5 bg-indigo-50 text-indigo-700 rounded text-xs"
                                  title={ta.target_name}
                                >
                                  {tid.slice(0, 6)}: {ta.affinity?.toFixed(2)}
                                </span>
                              ))}
                            </div>
                          </td>
                          <td className="py-2 px-2">
                            <span className="font-bold text-primary-600">{m.composite_score?.toFixed(4)}</span>
                          </td>
                          <td className="py-2 px-2">
                            <span className={`px-2 py-0.5 rounded text-xs ${
                              (m.properties?.druglikeness_score || 0) >= 70
                                ? 'bg-green-100 text-green-700'
                                : (m.properties?.druglikeness_score || 0) >= 50
                                  ? 'bg-yellow-100 text-yellow-700'
                                  : 'bg-red-100 text-red-700'
                            }`}>
                              {m.properties?.druglikeness_score?.toFixed(0) || '—'}/100
                            </span>
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              ) : (
                <div className="text-center py-4 text-gray-400">暂无设计结果</div>
              )}
            </Card>
          )}
        </div>
      </div>
    </div>
  );
}
