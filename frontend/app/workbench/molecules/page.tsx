'use client';

import { useState } from 'react';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { Atom, X, FlaskConical, Plus, Gauge, Microscope, ScanSearch } from 'lucide-react';
import {
  getMolecules, designMolecule, assessDruglikeness,
  predictProperties, explainMolecule,
} from '@/lib/api';
import Card from '@/components/ui/Card';
import Button from '@/components/ui/Button';
import Badge from '@/components/ui/Badge';
import PlotlyChart from '@/components/charts/PlotlyChart';

export default function MoleculesPage() {
  const [detail, setDetail] = useState<any>(null);
  const [showDesign, setShowDesign] = useState(false);
  const [showAssess, setShowAssess] = useState(false);
  const [assessResult, setAssessResult] = useState<any>(null);
  const [designResult, setDesignResult] = useState<any>(null);
  const [showAdmet, setShowAdmet] = useState(false);
  const [showExplain, setShowExplain] = useState(false);
  const [admetResult, setAdmetResult] = useState<any>(null);
  const [explainResult, setExplainResult] = useState<any>(null);
  const queryClient = useQueryClient();

  const { data: molecules, isLoading } = useQuery({
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

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold">分子库</h1>
          <p className="text-sm text-gray-500 mt-1">已设计/已批准的候选分子 — SMILES、类药性、对接结果</p>
        </div>
        <div className="flex gap-2">
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
        </div>
      </div>

      <Card title={`分子列表 (${molecules?.length || 0})`}>
        {isLoading ? (
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
                      <Button size="sm" variant="ghost" onClick={() => setDetail(m)}>
                        详情
                      </Button>
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
                          detail.properties.psa || 0,
                          detail.molecular_weight || 0,
                        ],
                        theta: ['MW', 'LogP', 'HBD', 'HBA', 'PSA', 'MW'],
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
