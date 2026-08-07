'use client';

import { useState, useEffect } from 'react';
import { useQuery } from '@tanstack/react-query';
import { unimolDock, vinaDock, hybridDock, type DockingMode } from '@/lib/api';
import { getTargets, getMolecules } from '@/lib/api';
import { Combine, Loader2, AlertCircle, Target as TargetIcon, ChevronDown, ChevronUp, Atom as MoleculeIcon, Zap } from 'lucide-react';
import { useAppStore } from '@/lib/store';
import TargetSelect from '@/components/TargetSelect';
import MoleculeStructure from '@/components/molecules/MoleculeStructure';
import Molecule3DViewer from '@/components/molecules/Molecule3DViewer';
import PoseValidationPanel from '@/components/molecules/PoseValidationPanel';
import AIInsightBanner from '@/components/coscientist/AIInsightBanner';

const MODES: { value: DockingMode; label: string; hint: string }[] = [
  { value: 'hybrid', label: 'Hybrid（LLM + 计算）', hint: '5 步 LLM-as-Controller 流程，最准但最慢' },
  { value: 'unimol', label: 'Uni-Mol 粗筛', hint: 'AI 对接，速度快' },
  { value: 'vina', label: 'Vina 精修', hint: '物理对接，需受体 PDBQT' },
];

export default function DockingPage() {
  const { currentProject } = useAppStore();
  const [smiles, setSmiles] = useState('');
  const [mode, setMode] = useState<DockingMode>('hybrid');
  const [targetId, setTargetId] = useState('');
  const [loading, setLoading] = useState(false);
  const [result, setResult] = useState<Record<string, unknown> | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [showMoleculePicker, setShowMoleculePicker] = useState(false);
  // Vina 对接参数
  const [boxCenter, setBoxCenter] = useState<[number, number, number]>([0, 0, 0]);
  const [boxSize, setBoxSize] = useState<[number, number, number]>([20, 20, 20]);
  const [exhaustiveness, setExhaustiveness] = useState(8);
  const [numPoses, setNumPoses] = useState(10);

  // 加载靶点对应的分子列表
  const { data: moleculesData, isLoading: moleculesLoading } = useQuery({
    queryKey: ['molecules-for-docking', targetId],
    queryFn: () => getMolecules(targetId || undefined),
    enabled: !!targetId,
  });
  const targetMolecules = (((moleculesData as any)?.data ?? (moleculesData as any)?.items) || (Array.isArray(moleculesData) ? moleculesData : []) || []) as any[];

  // 加载靶点信息（用于显示靶点基因、是否有预测结构）
  const { data: targetsData } = useQuery({
    queryKey: ['targets-for-docking'],
    queryFn: () => getTargets(),
  });
  const selectedTarget = (((targetsData as any)?.data ?? (targetsData as any)?.items) || (Array.isArray(targetsData) ? targetsData : []) || []).find(
    (t: any) => t.id === targetId
  );

  // 选择靶点后清空 SMILES（让用户重新选择分子）
  useEffect(() => {
    if (targetId) {
      setShowMoleculePicker(true);
    }
  }, [targetId]);

  // 从分子列表中选择分子，自动填充 SMILES
  const handlePickMolecule = (mol: any) => {
    setSmiles(mol.smiles || '');
    setShowMoleculePicker(false);
  };

  const handleDock = async () => {
    if (!smiles.trim()) return;
    setLoading(true);
    setError(null);
    setResult(null);
    try {
      let r: any;
      if (mode === 'hybrid') {
        if (!targetId.trim()) {
          setError('Hybrid 模式需要 target_id，请在上方选择靶点');
          setLoading(false);
          return;
        }
        r = await hybridDock({
          target_id: targetId.trim(),
          smiles_list: [smiles.trim()],
          top_k: 5,
        });
      } else if (mode === 'unimol') {
        r = await unimolDock({
          smiles: smiles.trim(),
          target_name: selectedTarget?.gene_symbol || '',
        });
      } else {
        r = await vinaDock({
          smiles: smiles.trim(),
          box: { center: boxCenter, size: boxSize },
          exhaustiveness,
          num_poses: numPoses,
        });
      }
      // 解包 data 信封
      const unwrapped = (r as any)?.data ?? r;
      setResult(unwrapped as Record<string, unknown>);
    } catch (e: unknown) {
      const err = e as { response?: { data?: { detail?: string; message?: string } }; message?: string };
      setError(err.response?.data?.detail || err.response?.data?.message || err.message || '对接失败');
    } finally {
      setLoading(false);
    }
  };

  // 解析对接结果（兼容 unimol/vina/hybrid 不同返回结构）
  const parsedResult = (() => {
    if (!result) return null;
    // Hybrid 模式返回 final_ranking + docking_results + report
    if (mode === 'hybrid') {
      const finalRanking = (result.final_ranking || []) as any[];
      const dockingResults = (result.docking_results || []) as any[];
      const report = (result.report || '') as string;
      return { type: 'hybrid', finalRanking, dockingResults, report };
    }
    // 单分子对接返回 {rmsd, affinity, confidence, binding_pose, source}
    return {
      type: 'single',
      rmsd: result.rmsd as number,
      affinity: result.affinity as number,
      confidence: result.confidence as number,
      binding_pose: result.binding_pose as any,
      source: result.source as string,
    };
  })();

  return (
    <div className="space-y-4">
      <div>
        <h1 className="text-2xl font-bold flex items-center gap-2">
          <Combine className="w-6 h-6 text-primary-600" />
          分子对接
        </h1>
        <p className="text-sm text-slate-500 mt-1">
          三模式对接：Hybrid（LLM + Uni-Mol + Vina）/ Uni-Mol AI 对接 / Vina 物理对接
        </p>
        <div className="mt-2 bg-blue-50 border border-blue-200 rounded p-3 text-xs text-blue-800">
          💡 <strong>使用提示：</strong>
          {mode === 'hybrid' ? '先在上方选择靶点，下方会自动弹出该靶点关联的分子列表供选择，免去手工输入 SMILES。Hybrid 模式是 5 步 LLM 流程，预计 30-90 秒，请耐心等待。'
            : '可直接输入 SMILES，或先选择靶点从分子库中挑选。'}
        </div>
      </div>

      <AIInsightBanner entityType="docking_job" projectId={currentProject?.id} />

      <div className="bg-white border rounded-lg p-4 space-y-3">
        {/* 靶点选择 */}
        <div>
          <label className="text-sm font-medium flex items-center gap-1">
            <TargetIcon className="w-3.5 h-3.5" />
            靶点（选择后会自动弹出关联分子列表）
          </label>
          <div className="mt-1">
            <TargetSelect
              value={targetId}
              onChange={setTargetId}
              projectId={currentProject?.id}
              placeholder="选择已发现的靶点（无需手工复制 ID）"
            />
          </div>
          {selectedTarget && (
            <div className="mt-2 p-2 bg-blue-50 border border-blue-100 rounded text-xs text-blue-800 flex items-center justify-between">
              <div>
                <strong>{selectedTarget.gene_symbol}</strong>
                {selectedTarget.gene_name ? ` · ${selectedTarget.gene_name}` : ''}
                {selectedTarget.confidence_score != null && ` · 置信度 ${(selectedTarget.confidence_score * 100).toFixed(1)}%`}
              </div>
              {targetMolecules.length > 0 && (
                <span className="px-2 py-0.5 bg-blue-100 rounded">关联分子 {targetMolecules.length} 个</span>
              )}
            </div>
          )}
          {targetId && (
            <div className="text-[10px] text-gray-400 mt-1 font-mono">target_id = {targetId}</div>
          )}
        </div>

        {/* 分子选择器（选择靶点后弹出） */}
        {targetId && targetMolecules.length > 0 && (
          <div className="border border-blue-200 rounded-lg bg-blue-50/30 overflow-hidden">
            <button
              onClick={() => setShowMoleculePicker((s) => !s)}
              className="w-full px-3 py-2 text-left flex items-center justify-between text-sm font-medium text-blue-800 hover:bg-blue-50"
            >
              <span className="flex items-center gap-2">
                <MoleculeIcon className="w-4 h-4" />
                选择该靶点关联的分子（共 {targetMolecules.length} 个）
              </span>
              {showMoleculePicker ? <ChevronUp className="w-4 h-4" /> : <ChevronDown className="w-4 h-4" />}
            </button>
            {showMoleculePicker && (
              <div className="max-h-72 overflow-y-auto border-t border-blue-200">
                {moleculesLoading ? (
                  <div className="p-4 text-center text-xs text-gray-400">加载中...</div>
                ) : (
                  <div className="grid grid-cols-1 md:grid-cols-2 gap-2 p-2">
                    {targetMolecules.map((mol: any) => (
                      <button
                        key={mol.id}
                        onClick={() => handlePickMolecule(mol)}
                        className={`flex gap-2 p-2 bg-white border rounded text-left hover:border-primary-400 hover:bg-primary-50 transition-colors ${
                          smiles === mol.smiles ? 'border-primary-500 bg-primary-50' : 'border-gray-200'
                        }`}
                      >
                        {mol.smiles && (
                          <div className="shrink-0">
                            <MoleculeStructure smiles={mol.smiles} width={80} height={60} />
                          </div>
                        )}
                        <div className="flex-1 min-w-0">
                          <div className="text-xs font-medium text-gray-800 truncate">
                            {mol.name || '未命名分子'}
                          </div>
                          <div className="font-mono text-[10px] text-gray-500 break-all">
                            {mol.smiles?.slice(0, 40)}{mol.smiles?.length > 40 ? '...' : ''}
                          </div>
                          <div className="flex items-center gap-2 mt-1 text-[10px] text-gray-500">
                            {mol.molecular_weight != null && <span>MW: {mol.molecular_weight.toFixed(0)}</span>}
                            {mol.logp != null && <span>LogP: {mol.logp.toFixed(1)}</span>}
                          </div>
                        </div>
                      </button>
                    ))}
                  </div>
                )}
              </div>
            )}
          </div>
        )}
        {targetId && targetMolecules.length === 0 && !moleculesLoading && (
          <div className="text-xs text-amber-700 bg-amber-50 border border-amber-200 p-2 rounded">
            该靶点暂无关联分子。请先在「分子库」中为该靶点设计分子，或直接手工输入 SMILES。
          </div>
        )}

        {/* SMILES 输入 */}
        <div>
          <label className="text-sm font-medium">SMILES</label>
          <input
            value={smiles}
            onChange={(e) => setSmiles(e.target.value)}
            placeholder="CC(=O)Oc1ccccc1C(=O)O 或从上方分子列表中选择"
            className="w-full px-3 py-2 border rounded font-mono text-sm"
          />
          {smiles && (
            <div className="mt-2 flex justify-center bg-gray-50 p-2 rounded">
              <MoleculeStructure smiles={smiles} width={200} height={140} />
            </div>
          )}
        </div>

        {/* 对接模式选择 */}
        <div>
          <label className="text-sm font-medium">对接模式</label>
          <div className="grid grid-cols-3 gap-2 mt-1">
            {MODES.map((m) => (
              <button
                key={m.value}
                onClick={() => setMode(m.value)}
                className={`px-3 py-2 text-sm rounded border ${
                  mode === m.value
                    ? 'bg-primary-600 text-white border-primary-600'
                    : 'bg-white text-slate-700 border-slate-300 hover:border-primary-400'
                }`}
                title={m.hint}
              >
                {m.label}
              </button>
            ))}
          </div>
          <div className="text-xs text-gray-500 mt-1">
            {MODES.find((m) => m.value === mode)?.hint}
          </div>
        </div>

        {/* Vina 对接参数面板（仅 Vina 模式显示） */}
        {mode === 'vina' && (
          <div className="border border-blue-200 rounded-lg bg-blue-50/30 p-3 space-y-3">
            <div className="text-sm font-medium text-blue-800">Vina 对接参数</div>
            <div className="grid grid-cols-2 md:grid-cols-3 gap-3">
              <div>
                <label className="text-xs text-gray-500">Box Center X</label>
                <input
                  type="number"
                  value={boxCenter[0]}
                  onChange={(e) => setBoxCenter([Number(e.target.value), boxCenter[1], boxCenter[2]])}
                  className="w-full px-2 py-1 border rounded text-sm"
                />
              </div>
              <div>
                <label className="text-xs text-gray-500">Box Center Y</label>
                <input
                  type="number"
                  value={boxCenter[1]}
                  onChange={(e) => setBoxCenter([boxCenter[0], Number(e.target.value), boxCenter[2]])}
                  className="w-full px-2 py-1 border rounded text-sm"
                />
              </div>
              <div>
                <label className="text-xs text-gray-500">Box Center Z</label>
                <input
                  type="number"
                  value={boxCenter[2]}
                  onChange={(e) => setBoxCenter([boxCenter[0], boxCenter[1], Number(e.target.value)])}
                  className="w-full px-2 py-1 border rounded text-sm"
                />
              </div>
              <div>
                <label className="text-xs text-gray-500">Box Size X (Å)</label>
                <input
                  type="number"
                  value={boxSize[0]}
                  onChange={(e) => setBoxSize([Number(e.target.value), boxSize[1], boxSize[2]])}
                  className="w-full px-2 py-1 border rounded text-sm"
                />
              </div>
              <div>
                <label className="text-xs text-gray-500">Box Size Y (Å)</label>
                <input
                  type="number"
                  value={boxSize[1]}
                  onChange={(e) => setBoxSize([boxSize[0], Number(e.target.value), boxSize[2]])}
                  className="w-full px-2 py-1 border rounded text-sm"
                />
              </div>
              <div>
                <label className="text-xs text-gray-500">Box Size Z (Å)</label>
                <input
                  type="number"
                  value={boxSize[2]}
                  onChange={(e) => setBoxSize([boxSize[0], boxSize[1], Number(e.target.value)])}
                  className="w-full px-2 py-1 border rounded text-sm"
                />
              </div>
            </div>
            <div className="grid grid-cols-2 gap-3">
              <div>
                <label className="text-xs text-gray-500">Exhaustiveness（搜索深度: {exhaustiveness}）</label>
                <input
                  type="range"
                  min={1}
                  max={32}
                  value={exhaustiveness}
                  onChange={(e) => setExhaustiveness(Number(e.target.value))}
                  className="w-full"
                />
              </div>
              <div>
                <label className="text-xs text-gray-500">Num Poses（输出构象数）</label>
                <input
                  type="number"
                  min={1}
                  max={20}
                  value={numPoses}
                  onChange={(e) => setNumPoses(Number(e.target.value))}
                  className="w-full px-2 py-1 border rounded text-sm"
                />
              </div>
            </div>
          </div>
        )}

        <button
          onClick={handleDock}
          disabled={!smiles.trim() || loading || (mode === 'hybrid' && !targetId.trim())}
          className="flex items-center gap-2 px-4 py-2 bg-primary-600 text-white rounded hover:bg-primary-700 disabled:opacity-50"
        >
          {loading && <Loader2 className="w-4 h-4 animate-spin" />}
          {loading
            ? (mode === 'hybrid'
                ? 'Hybrid 对接中（5 步 LLM 流程，预计 30-90 秒）...'
                : mode === 'unimol'
                ? 'Uni-Mol AI 对接中...'
                : 'Vina 物理对接中...')
            : '开始对接'}
        </button>
        {loading && mode === 'hybrid' && (
          <div className="mt-2 text-xs text-amber-700 bg-amber-50 border border-amber-200 p-2 rounded">
            ⏳ 正在执行 5 步 LLM-as-Controller 流程：① LLM 假设生成 → ② Uni-Mol 并发粗筛 → ③ LLM 重排序 → ④ Vina 并发精修 → ⑤ LLM 综合报告。请勿关闭页面。
          </div>
        )}
      </div>

      {error && (
        <div className="flex items-start gap-2 px-3 py-2 bg-red-50 text-red-700 border border-red-200 rounded text-sm">
          <AlertCircle className="w-4 h-4 mt-0.5 shrink-0" />
          <div>{error}</div>
        </div>
      )}

      {/* 对接结果展示 */}
      {parsedResult && (
        <div className="space-y-3">
          {parsedResult.type === 'single' ? (
            <>
              {/* 单分子对接结果卡片 */}
              <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
                <div className="bg-gradient-to-br from-blue-50 to-cyan-50 border border-blue-100 rounded-lg p-4">
                  <div className="text-xs text-gray-500">结合亲和力</div>
                  <div className="text-xl font-bold text-blue-700 mt-1">
                    {parsedResult.affinity != null ? parsedResult.affinity.toFixed(2) : '—'}
                  </div>
                  <div className="text-xs text-gray-500 mt-1">kcal/mol（越负越好）</div>
                </div>
                <div className="bg-gradient-to-br from-green-50 to-emerald-50 border border-green-100 rounded-lg p-4">
                  <div className="text-xs text-gray-500">RMSD</div>
                  <div className="text-xl font-bold text-green-700 mt-1">
                    {parsedResult.rmsd != null ? parsedResult.rmsd.toFixed(2) : '—'}
                  </div>
                  <div className="text-xs text-gray-500 mt-1">Å（越小越好）</div>
                </div>
                <div className="bg-gradient-to-br from-purple-50 to-pink-50 border border-purple-100 rounded-lg p-4">
                  <div className="text-xs text-gray-500">置信度</div>
                  <div className="text-xl font-bold text-purple-700 mt-1">
                    {parsedResult.confidence != null ? (parsedResult.confidence * 100).toFixed(1) + '%' : '—'}
                  </div>
                  <div className="text-xs text-gray-500 mt-1">模型置信度</div>
                </div>
                <div className="bg-gradient-to-br from-orange-50 to-amber-50 border border-orange-100 rounded-lg p-4">
                  <div className="text-xs text-gray-500">对接来源</div>
                  <div className="text-sm font-bold text-orange-700 mt-1 uppercase">
                    {parsedResult.source || '—'}
                  </div>
                  <div className="text-xs text-gray-500 mt-1">mock/真实引擎</div>
                </div>
              </div>

              {/* 扩展评估指标（Ki / 配体效率 / Lipinski） */}
              {((parsedResult as any).ki != null || (parsedResult as any).ligand_efficiency != null) && (
                <div className="grid grid-cols-2 md:grid-cols-3 gap-3">
                  {(parsedResult as any).ki != null && (
                    <div className="bg-gradient-to-br from-cyan-50 to-teal-50 border border-cyan-100 rounded-lg p-4">
                      <div className="text-xs text-gray-500">抑制常数 Ki</div>
                      <div className="text-xl font-bold text-cyan-700 mt-1">
                        {(parsedResult as any).ki.toFixed(2)}
                      </div>
                      <div className="text-xs text-gray-500 mt-1">μM（越小越好）</div>
                    </div>
                  )}
                  {(parsedResult as any).ligand_efficiency != null && (
                    <div className="bg-gradient-to-br from-indigo-50 to-blue-50 border border-indigo-100 rounded-lg p-4">
                      <div className="text-xs text-gray-500">配体效率</div>
                      <div className="text-xl font-bold text-indigo-700 mt-1">
                        {(parsedResult as any).ligand_efficiency.toFixed(3)}
                      </div>
                      <div className="text-xs text-gray-500 mt-1">kcal/mol per 重原子</div>
                    </div>
                  )}
                  {parsedResult.binding_pose?.lipinski_pass != null && (
                    <div className="bg-gradient-to-br from-emerald-50 to-green-50 border border-emerald-100 rounded-lg p-4">
                      <div className="text-xs text-gray-500">Lipinski 五规则</div>
                      <div className="text-xl font-bold text-emerald-700 mt-1">
                        {parsedResult.binding_pose.lipinski_pass ? '通过' : '不通过'}
                      </div>
                      <div className="text-xs text-gray-500 mt-1">类药性判断</div>
                    </div>
                  )}
                </div>
              )}

              {/* 3D 结合姿态可视化 */}
              {parsedResult.binding_pose?.mol_block && (
                <div className="bg-white border rounded-lg p-4">
                  <h3 className="font-semibold mb-2 flex items-center gap-2">
                    <MoleculeIcon className="w-4 h-4 text-primary-600" />
                    3D 结合姿态可视化
                  </h3>
                  <Molecule3DViewer
                    molBlock={parsedResult.binding_pose.mol_block}
                    height={380}
                    spin
                  />
                </div>
              )}

              {/* 坐标验证面板 */}
              {parsedResult.binding_pose?.coordinates && (
                <PoseValidationPanel
                  coordinates={parsedResult.binding_pose.coordinates}
                  boxCenter={parsedResult.binding_pose.box_center}
                  boxSize={parsedResult.binding_pose.box_size}
                  rmsd={parsedResult.rmsd}
                  atomCount={parsedResult.binding_pose.atom_count}
                  heavyAtomCount={parsedResult.binding_pose.heavy_atom_count}
                />
              )}
            </>
          ) : (
            <>
              {/* Hybrid 模式结果 */}
              <div className="bg-gradient-to-br from-indigo-50 to-purple-50 border border-indigo-200 rounded-lg p-4">
                <div className="flex items-center gap-2 text-indigo-800 font-semibold mb-2">
                  <Zap className="w-5 h-5" />
                  LLM 驱动 Hybrid 对接报告
                </div>
                <div className="grid grid-cols-2 md:grid-cols-4 gap-2 text-xs">
                  <div className="bg-white p-2 rounded">
                    <div className="text-gray-500">完成步骤</div>
                    <div className="font-bold text-indigo-700">{(result as any).steps_completed || '—'}</div>
                  </div>
                  <div className="bg-white p-2 rounded">
                    <div className="text-gray-500">耗时</div>
                    <div className="font-bold text-indigo-700">{(result as any).duration_sec?.toFixed(1) || '—'}s</div>
                  </div>
                  <div className="bg-white p-2 rounded">
                    <div className="text-gray-500">LLM 成本</div>
                    <div className="font-bold text-indigo-700">${(result as any).cost_usd?.toFixed(4) || '—'}</div>
                  </div>
                  <div className="bg-white p-2 rounded">
                    <div className="text-gray-500">是否截断</div>
                    <div className="font-bold text-indigo-700">{(result as any).truncated ? '是' : '否'}</div>
                  </div>
                </div>
              </div>

              {/* 最终排名 */}
              {parsedResult.finalRanking.length > 0 && (
                <div className="bg-white border rounded-lg p-4">
                  <h3 className="font-semibold mb-3">最终排名（LLM 重排序后）</h3>
                  <div className="overflow-x-auto">
                    <table className="w-full text-sm">
                      <thead>
                        <tr className="border-b text-left text-gray-500">
                          <th className="pb-2">排名</th>
                          <th className="pb-2">SMILES</th>
                          <th className="pb-2">结构式</th>
                          <th className="pb-2">亲和力</th>
                          <th className="pb-2">RMSD</th>
                          <th className="pb-2">综合评分</th>
                        </tr>
                      </thead>
                      <tbody>
                        {parsedResult.finalRanking.map((r: any, i: number) => (
                          <tr key={i} className={`border-b ${i === 0 ? 'bg-amber-50' : ''}`}>
                            <td className="py-2 pr-3">
                              <span className={`px-2 py-0.5 rounded text-xs font-bold ${i === 0 ? 'bg-amber-200 text-amber-800' : 'bg-gray-100 text-gray-700'}`}>
                                #{i + 1}
                              </span>
                            </td>
                            <td className="py-2 pr-3 font-mono text-xs text-gray-600 max-w-xs truncate" title={r.smiles}>
                              {r.smiles}
                            </td>
                            <td className="py-2 pr-3">
                              {r.smiles && <MoleculeStructure smiles={r.smiles} width={80} height={60} />}
                            </td>
                            <td className="py-2 pr-3 text-blue-700 font-medium">
                              {r.affinity != null ? r.affinity.toFixed(2) : '—'}
                            </td>
                            <td className="py-2 pr-3 text-green-700">
                              {r.rmsd != null ? r.rmsd.toFixed(2) : '—'}
                            </td>
                            <td className="py-2 pr-3">
                              {r.score != null && (
                                <div className="flex items-center gap-2">
                                  <div className="w-16 h-2 bg-gray-100 rounded overflow-hidden">
                                    <div className="h-full bg-primary-500" style={{ width: `${Math.min(100, r.score * 100)}%` }} />
                                  </div>
                                  <span className="text-primary-700 font-medium">{r.score.toFixed(3)}</span>
                                </div>
                              )}
                            </td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                </div>
              )}

              {/* LLM 报告 */}
              {parsedResult.report && (
                <div className="bg-blue-50 border border-blue-200 rounded-lg p-4">
                  <div className="flex items-center gap-2 text-blue-800 font-semibold mb-2">
                    <Zap className="w-4 h-4" />
                    LLM 综合报告
                  </div>
                  <p className="text-sm text-blue-700 whitespace-pre-wrap">{parsedResult.report}</p>
                </div>
              )}
            </>
          )}

          {/* 完整 JSON 结果（折叠） */}
          <div className="bg-white border rounded-lg p-4">
            <details>
              <summary className="text-sm text-primary-600 cursor-pointer hover:text-primary-700">
                查看完整结果 JSON
              </summary>
              <pre className="mt-3 p-2 bg-slate-50 text-xs font-mono overflow-auto max-h-96 rounded">
                {JSON.stringify(result, null, 2)}
              </pre>
            </details>
          </div>
        </div>
      )}
    </div>
  );
}
