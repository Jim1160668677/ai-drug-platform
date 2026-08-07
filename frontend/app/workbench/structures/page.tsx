'use client';

import { useState, useEffect } from 'react';
import { useQuery } from '@tanstack/react-query';
import {
  predictStructure,
  type ProteinStructure,
  type PredictStructureResult,
  type StructureEngine,
} from '@/lib/api';
import { getTargets, getMolecules, getTargetProteinSequence } from '@/lib/api';
import {
  Box,
  Loader2,
  AlertCircle,
  Download,
  Activity,
  Boxes,
  Target as TargetIcon,
  ChevronDown,
  ChevronUp,
  Pill,
  Sparkles,
} from 'lucide-react';
import { useAppStore } from '@/lib/store';
import TargetSelect from '@/components/TargetSelect';
import MoleculeStructure from '@/components/molecules/MoleculeStructure';
import ProteinStructure3D from '@/components/protein/ProteinStructure3D';
import AIInsightBanner from '@/components/coscientist/AIInsightBanner';

type Engine = 'auto' | StructureEngine;

const ENGINE_OPTIONS: { value: Engine; label: string; hint: string }[] = [
  { value: 'auto', label: '自动（推荐）', hint: '传配体自动用 Protenix，否则用 ESMFold' },
  { value: 'esmfold', label: 'ESMFold（仅蛋白）', hint: 'Facebook ESMFold，仅预测蛋白主链' },
  { value: 'protenix', label: 'Protenix（蛋白+配体）', hint: '字节 Protenix，预测复合物并输出结合位点' },
];

export default function StructuresPage() {
  const { currentProject } = useAppStore();
  const [sequence, setSequence] = useState('');
  const [ligandSmiles, setLigandSmiles] = useState('');
  const [engine, setEngine] = useState<Engine>('auto');
  const [targetId, setTargetId] = useState('');
  const [showMoleculePicker, setShowMoleculePicker] = useState(false);
  const [loading, setLoading] = useState(false);
  const [result, setResult] = useState<PredictStructureResult | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [uniprotInfo, setUniProtInfo] = useState<any>(null);
  const [sequenceLoading, setSequenceLoading] = useState(false);

  // 加载靶点对应的分子列表（用于选择配体）
  const { data: moleculesData, isLoading: moleculesLoading } = useQuery({
    queryKey: ['molecules-for-structure', targetId],
    queryFn: () => getMolecules(targetId || undefined),
    enabled: !!targetId,
  });
  const targetMolecules = (((moleculesData as any)?.data ?? (moleculesData as any)?.items) || (Array.isArray(moleculesData) ? moleculesData : []) || []) as any[];

  // 加载靶点信息（用于自动填充蛋白序列）
  const { data: targetsData } = useQuery({
    queryKey: ['targets-for-structure'],
    queryFn: () => getTargets(),
  });
  const selectedTarget = (((targetsData as any)?.data ?? (targetsData as any)?.items) || (Array.isArray(targetsData) ? targetsData : []) || []).find(
    (t: any) => t.id === targetId
  ) as any;

  // 选择靶点后：① 先尝试本地缓存填充序列 ② 缓存无则查询 UniProt API ③ 弹出分子列表
  // 合并为单个 useEffect，避免两个 effect 竞态导致 UniProt 被重复查询
  useEffect(() => {
    if (!targetId) return;
    let cancelled = false;

    // 弹出关联分子列表（如果有）
    if (targetMolecules.length > 0) {
      setShowMoleculePicker(true);
    }

    // Step 1: 优先用本地缓存填充蛋白序列
    if (selectedTarget) {
      const annotation = (selectedTarget.annotation && typeof selectedTarget.annotation === 'object') ? selectedTarget.annotation : {};
      const cachedSeq = selectedTarget.target_sequence || annotation.protein_sequence || '';
      if (cachedSeq) {
        setSequence(cachedSeq);
        setUniProtInfo({
          source: 'cache',
          uniprot_id: annotation.uniprot_id || '',
          protein_name: annotation.protein_name || '',
          sequence_length: cachedSeq.length,
        });
        return;  // 缓存命中，无需查询 UniProt
      }
    }

    // Step 2: 本地无序列，调用 UniProt API 自动填充
    setSequenceLoading(true);
    setUniProtInfo(null);
    (async () => {
      try {
        const result: any = await getTargetProteinSequence(targetId);
        if (cancelled || !result) return;
        if (result.source === 'uniprot' || result.source === 'cache') {
          const seq = result.sequence || '';
          if (seq) {
            setSequence(seq);
            setUniProtInfo({
              source: result.source,
              uniprot_id: result.uniprot_id || '',
              protein_name: result.protein_name || '',
              sequence_length: result.sequence_length || seq.length,
            });
          } else {
            setUniProtInfo({ source: 'error', error: 'UniProt 未返回序列' });
          }
        } else if (result.source === 'error') {
          setUniProtInfo({ source: 'error', error: result.error || '查询失败' });
        }
      } catch (e) {
        if (!cancelled) {
          setUniProtInfo({ source: 'error', error: (e as Error)?.message || 'UniProt 查询失败' });
        }
      } finally {
        if (!cancelled) setSequenceLoading(false);
      }
    })();

    return () => { cancelled = true; };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [targetId, selectedTarget?.id]);

  // 选择分子后自动填充 ligand_smiles
  const handlePickMolecule = (mol: any) => {
    setLigandSmiles(mol.smiles || '');
    setShowMoleculePicker(false);
  };

  const handlePredict = async () => {
    if (!sequence.trim()) return;
    setLoading(true);
    setError(null);
    try {
      // 决定引擎：auto 模式下，有 ligand_smiles 则用 protenix
      const useProtenix =
        engine === 'protenix' || (engine === 'auto' && !!ligandSmiles.trim());

      const payload: any = {
        sequence: sequence.trim(),
        target_id: targetId || undefined,
      };
      if (engine !== 'auto') payload.engine = engine;
      if (ligandSmiles.trim()) payload.ligand_smiles = ligandSmiles.trim();

      const r = await predictStructure(payload);
      setResult(r);
      // 引擎实际选择日志（用于前端展示）
      if (useProtenix && !r.ligand_coordinates) {
        // 后端可能没识别 protenix，前端给提示
        console.warn('Protenix 模式预期返回 ligand_coordinates，但未返回');
      }
    } catch (e: unknown) {
      const err = e as { response?: { data?: { detail?: string; message?: string } }; message?: string };
      setError(err.response?.data?.detail || err.response?.data?.message || err.message || '预测失败');
    } finally {
      setLoading(false);
    }
  };

  const handleDownloadPDB = () => {
    if (!result?.pdb_text) return;
    const blob = new Blob([result.pdb_text], { type: 'chemical/x-pdb' });
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = `protein_structure_${result.structure_id || 'unknown'}.pdb`;
    document.body.appendChild(a);
    a.click();
    document.body.removeChild(a);
    URL.revokeObjectURL(url);
  };

  // 加载示例序列（p53 DNA 结合域，常用测试序列）
  const handleLoadExample = () => {
    setSequence(
      'MEEPQSDPSVEPPLSQETFSDLWKLLPENNVLSPLPSQAMDDLMLSPDDIEQWFTEDPGP'
        + 'DEAPRMPEAAPPVAPAPAAPTPAAPAPAPSWPLSSSVPSQKTYQGSYGFRLGFLHSGTAK'
        + 'SVTCTYSPALNKMFCQLAKTCPVQLWVDSTPPPGTRVRAMAIYKQSQHMTEVVRRCPHHE'
        + 'RCSDSDGLAPPQHLIRVEGNLRVEYLDDRNTFRHSVVVPYEPPEVGSDCTTIHYNYMCNS'
        + 'SCMGGMNRRPILTIITLEDSSGNLLGRNSFEVRVCACPGRDRRTEEENLRKKGEPHHELP'
        + 'PGSTKRALPNNTSSSPQPKKKPLDGEYFTLQIRGRERFEMFRELNEALELKDAHATEESG'
        + 'DSALTMANSSSPVKNKLFDSVGLFGKIINT'
    );
  };

  const pdbText = result?.pdb_text;
  const plddtMean = typeof result?.plddt_mean === 'number' ? result.plddt_mean : undefined;
  const ligandCoords = result?.ligand_coordinates;
  const bindingSite = result?.binding_site_residues;
  const usedProtenix = !!ligandCoords || (result?.source || '').includes('protenix');

  return (
    <div className="space-y-4">
      <div>
        <h1 className="text-2xl font-bold flex items-center gap-2">
          <Box className="w-6 h-6 text-primary-600" />
          蛋白结构预测
        </h1>
        <p className="text-sm text-slate-500 mt-1">
          双引擎：ESMFold（仅蛋白）+ 字节 Protenix（蛋白-配体复合物 + 结合位点）。
          支持 AlphaFold 风格 3D 可视化，按 pLDDT 着色，并可高亮显示小分子药物与蛋白结合的具体位点。
        </p>
      </div>

      <AIInsightBanner entityType="structure" projectId={currentProject?.id} />

      <div className="bg-white border rounded-lg p-4 space-y-3">
        {/* 靶点选择 */}
        <div>
          <label className="text-sm font-medium flex items-center gap-1">
            <TargetIcon className="w-3.5 h-3.5" />
            关联靶点（选择后会自动填充蛋白序列与配体列表）
          </label>
          <div className="mt-1">
            <TargetSelect
              value={targetId}
              onChange={setTargetId}
              projectId={currentProject?.id}
              placeholder="选择已发现的靶点（无需手工复制序列）"
            />
          </div>
          {selectedTarget && (
            <div className="mt-2 p-2 bg-blue-50 border border-blue-100 rounded text-xs text-blue-800">
              <strong>{selectedTarget.gene_symbol}</strong>
              {selectedTarget.gene_name ? ` · ${selectedTarget.gene_name}` : ''}
              {selectedTarget.confidence_score != null && ` · 置信度 ${(selectedTarget.confidence_score * 100).toFixed(1)}%`}
              {selectedTarget.target_sequence && ` · 本地蛋白序列长度 ${selectedTarget.target_sequence.length}`}
            </div>
          )}

          {/* UniProt 序列查询状态 */}
          {targetId && sequenceLoading && (
            <div className="mt-2 p-2 bg-amber-50 border border-amber-200 rounded text-xs text-amber-800 flex items-center gap-2">
              <Loader2 className="w-3 h-3 animate-spin" />
              正在从 UniProt 数据库查询 <strong>{selectedTarget?.gene_symbol}</strong> 的 canonical 蛋白序列...
            </div>
          )}
          {targetId && uniprotInfo && uniprotInfo.source === 'uniprot' && (
            <div className="mt-2 p-2 bg-emerald-50 border border-emerald-200 rounded text-xs text-emerald-800 flex items-center justify-between flex-wrap gap-2">
              <div>
                ✓ UniProt 查询成功 ·
                <strong>{uniprotInfo.uniprot_id}</strong>
                {uniprotInfo.protein_name ? ` · ${uniprotInfo.protein_name}` : ''}
                {` · 序列长度 ${uniprotInfo.sequence_length} 残基`}
              </div>
              <button
                onClick={async () => {
                  // 强制重新查询 UniProt（refresh=true 跳过后端缓存）
                  try {
                    setSequenceLoading(true);
                    setUniProtInfo(null);
                    const result: any = await getTargetProteinSequence(targetId, true);
                    if (result.source === 'uniprot' || result.source === 'cache') {
                      setSequence(result.sequence || '');
                      setUniProtInfo({
                        source: result.source,
                        uniprot_id: result.uniprot_id || '',
                        protein_name: result.protein_name || '',
                        sequence_length: result.sequence_length || (result.sequence || '').length,
                      });
                    } else if (result.source === 'error') {
                      setUniProtInfo({ source: 'error', error: result.error || '查询失败' });
                    }
                  } catch (e) {
                    setUniProtInfo({ source: 'error', error: (e as Error)?.message || '重试失败' });
                  } finally {
                    setSequenceLoading(false);
                  }
                }}
                className="px-2 py-0.5 text-[10px] bg-emerald-100 hover:bg-emerald-200 border border-emerald-300 rounded text-emerald-800"
                title="强制重新查询 UniProt（跳过缓存）"
              >
                重新查询
              </button>
            </div>
          )}
          {targetId && uniprotInfo && uniprotInfo.source === 'cache' && (
            <div className="mt-2 p-2 bg-blue-50 border border-blue-200 rounded text-xs text-blue-700 flex items-center justify-between flex-wrap gap-2">
              <div>
                ✓ 已使用本地缓存的 UniProt 蛋白序列
                {uniprotInfo.uniprot_id ? ` · ${uniprotInfo.uniprot_id}` : ''}
              </div>
              <button
                onClick={async () => {
                  try {
                    setSequenceLoading(true);
                    setUniProtInfo(null);
                    const result: any = await getTargetProteinSequence(targetId, true);
                    if (result.source === 'uniprot' || result.source === 'cache') {
                      setSequence(result.sequence || '');
                      setUniProtInfo({
                        source: result.source,
                        uniprot_id: result.uniprot_id || '',
                        protein_name: result.protein_name || '',
                        sequence_length: result.sequence_length || (result.sequence || '').length,
                      });
                    } else if (result.source === 'error') {
                      setUniProtInfo({ source: 'error', error: result.error || '查询失败' });
                    }
                  } catch (e) {
                    setUniProtInfo({ source: 'error', error: (e as Error)?.message || '重试失败' });
                  } finally {
                    setSequenceLoading(false);
                  }
                }}
                className="px-2 py-0.5 text-[10px] bg-blue-100 hover:bg-blue-200 border border-blue-300 rounded text-blue-800"
                title="强制重新查询 UniProt（跳过缓存）"
              >
                刷新
              </button>
            </div>
          )}
          {targetId && uniprotInfo && uniprotInfo.source === 'error' && (
            <div className="mt-2 p-2 bg-red-50 border border-red-200 rounded text-xs text-red-700 flex items-center justify-between flex-wrap gap-2">
              <div>
                ⚠ UniProt 查询失败：{uniprotInfo.error}
                <span className="ml-2 text-gray-500">可手工在下方输入序列</span>
              </div>
              <button
                onClick={async () => {
                  try {
                    setSequenceLoading(true);
                    setUniProtInfo(null);
                    const result: any = await getTargetProteinSequence(targetId, true);
                    if (result.source === 'uniprot' || result.source === 'cache') {
                      setSequence(result.sequence || '');
                      setUniProtInfo({
                        source: result.source,
                        uniprot_id: result.uniprot_id || '',
                        protein_name: result.protein_name || '',
                        sequence_length: result.sequence_length || (result.sequence || '').length,
                      });
                    } else if (result.source === 'error') {
                      setUniProtInfo({ source: 'error', error: result.error || '查询失败' });
                    }
                  } catch (e) {
                    setUniProtInfo({ source: 'error', error: (e as Error)?.message || '重试失败' });
                  } finally {
                    setSequenceLoading(false);
                  }
                }}
                className="px-2 py-0.5 text-[10px] bg-red-100 hover:bg-red-200 border border-red-300 rounded text-red-800"
              >
                重试
              </button>
            </div>
          )}
        </div>

        {/* 氨基酸序列 */}
        <div>
          <div className="flex items-center justify-between">
            <label className="text-sm font-medium">氨基酸序列</label>
            <button
              onClick={handleLoadExample}
              className="text-xs text-primary-600 hover:text-primary-700"
              title="加载 p53 肿瘤抑制蛋白序列作为示例"
            >
              📋 加载示例（p53）
            </button>
          </div>
          <textarea
            value={sequence}
            onChange={(e) => setSequence(e.target.value)}
            placeholder="MKKLLLIVTAAHCLGGSFVGDVNSNE... 或选择靶点后自动填充"
            rows={4}
            className="w-full px-3 py-2 border rounded font-mono text-sm"
          />
        </div>

        {/* 配体 SMILES（可选 — Protenix 复合物预测） */}
        <div>
          <label className="text-sm font-medium flex items-center gap-1">
            <Pill className="w-3.5 h-3.5" />
            配体 SMILES（可选 — 填写后自动切换 Protenix 预测复合物结构与结合位点）
          </label>
          {/* 分子选择器 */}
          {targetId && targetMolecules.length > 0 && (
            <div className="mt-1 border border-blue-200 rounded-lg bg-blue-50/30 overflow-hidden">
              <button
                onClick={() => setShowMoleculePicker((s) => !s)}
                className="w-full px-3 py-2 text-left flex items-center justify-between text-sm font-medium text-blue-800 hover:bg-blue-50"
              >
                <span className="flex items-center gap-2">
                  <Sparkles className="w-4 h-4" />
                  从该靶点关联分子库中选择配体（共 {targetMolecules.length} 个）
                </span>
                {showMoleculePicker ? <ChevronUp className="w-4 h-4" /> : <ChevronDown className="w-4 h-4" />}
              </button>
              {showMoleculePicker && (
                <div className="max-h-60 overflow-y-auto border-t border-blue-200">
                  {moleculesLoading ? (
                    <div className="p-4 text-center text-xs text-gray-400">加载中...</div>
                  ) : (
                    <div className="grid grid-cols-1 md:grid-cols-2 gap-2 p-2">
                      {targetMolecules.map((mol: any) => (
                        <button
                          key={mol.id}
                          onClick={() => handlePickMolecule(mol)}
                          className={`flex gap-2 p-2 bg-white border rounded text-left hover:border-primary-400 hover:bg-primary-50 transition-colors ${
                            ligandSmiles === mol.smiles ? 'border-primary-500 bg-primary-50' : 'border-gray-200'
                          }`}
                        >
                          {mol.smiles && (
                            <div className="shrink-0">
                              <MoleculeStructure smiles={mol.smiles} width={60} height={50} />
                            </div>
                          )}
                          <div className="flex-1 min-w-0">
                            <div className="text-xs font-medium text-gray-800 truncate">
                              {mol.name || '未命名分子'}
                            </div>
                            <div className="font-mono text-[10px] text-gray-500 break-all">
                              {mol.smiles?.slice(0, 30)}{mol.smiles?.length > 30 ? '...' : ''}
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
          <input
            value={ligandSmiles}
            onChange={(e) => setLigandSmiles(e.target.value)}
            placeholder="CC(=O)Oc1ccccc1C(=O)O（阿司匹林）— 留空则仅预测蛋白结构"
            className="w-full mt-1 px-3 py-2 border rounded font-mono text-sm"
          />
          {ligandSmiles && (
            <div className="mt-2 flex justify-center bg-gray-50 p-2 rounded">
              <MoleculeStructure smiles={ligandSmiles} width={200} height={120} />
            </div>
          )}
        </div>

        {/* 引擎选择 */}
        <div>
          <label className="text-sm font-medium">预测引擎</label>
          <div className="grid grid-cols-3 gap-2 mt-1">
            {ENGINE_OPTIONS.map((opt) => (
              <button
                key={opt.value}
                onClick={() => setEngine(opt.value)}
                className={`px-3 py-2 text-sm rounded border ${
                  engine === opt.value
                    ? 'bg-primary-600 text-white border-primary-600'
                    : 'bg-white text-slate-700 border-slate-300 hover:border-primary-400'
                }`}
                title={opt.hint}
              >
                {opt.label}
              </button>
            ))}
          </div>
          <div className="text-xs text-gray-500 mt-1">
            {ENGINE_OPTIONS.find((o) => o.value === engine)?.hint}
          </div>
        </div>

        <button
          onClick={handlePredict}
          disabled={!sequence.trim() || loading}
          className="flex items-center gap-2 px-4 py-2 bg-primary-600 text-white rounded hover:bg-primary-700 disabled:opacity-50"
        >
          {loading && <Loader2 className="w-4 h-4 animate-spin" />}
          {loading ? '预测中...' : usedProtenix ? '预测复合物结构' : '预测蛋白结构'}
        </button>
      </div>

      {error && (
        <div className="flex items-start gap-2 px-3 py-2 bg-red-50 text-red-700 border border-red-200 rounded text-sm">
          <AlertCircle className="w-4 h-4 mt-0.5 shrink-0" />
          <div>{error}</div>
        </div>
      )}

      {result && (
        <div className="bg-white border rounded-lg p-4 space-y-4">
          <div className="flex items-center justify-between">
            <h2 className="font-semibold flex items-center gap-2">
              <Boxes className="w-4 h-4 text-primary-600" />
              预测结果
              {usedProtenix && (
                <span className="px-2 py-0.5 text-[10px] bg-emerald-100 text-emerald-700 rounded-full">
                  Protenix 复合物
                </span>
              )}
            </h2>
            {pdbText && (
              <button
                onClick={handleDownloadPDB}
                className="flex items-center gap-1 px-3 py-1 text-xs bg-gray-100 hover:bg-gray-200 rounded text-gray-700"
                title="下载 PDB 文件"
              >
                <Download className="w-3 h-3" />
                下载 PDB
              </button>
            )}
          </div>

          <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
            <div className="bg-gradient-to-br from-blue-50 to-indigo-50 p-3 rounded border border-blue-100">
              <div className="text-xs text-gray-500 flex items-center gap-1">
                <Activity className="w-3 h-3" />
                平均 pLDDT
              </div>
              <div className="text-lg font-bold text-primary-700">
                {typeof plddtMean === 'number' ? (plddtMean * 100).toFixed(2) + '%' : '-'}
              </div>
              {typeof plddtMean === 'number' && (
                <div className="mt-1 h-2 bg-slate-200 rounded-full overflow-hidden">
                  <div
                    className="h-full bg-primary-500"
                    style={{ width: `${Math.min(100, Math.max(0, plddtMean * 100))}%` }}
                  />
                </div>
              )}
              <div className="text-[10px] text-gray-500 mt-1">
                {plddtMean != null && plddtMean >= 0.9
                  ? '高质量（可信）'
                  : plddtMean != null && plddtMean >= 0.7
                  ? '中等（构架可信）'
                  : plddtMean != null && plddtMean >= 0.5
                  ? '低（谨慎使用）'
                  : plddtMean != null
                  ? '极低（不可信）'
                  : ''}
              </div>
            </div>
            <div className="bg-gray-50 p-3 rounded">
              <div className="text-xs text-gray-500">引擎</div>
              <div className="text-sm font-medium">{result.source || '-'}</div>
            </div>
            <div className="bg-gray-50 p-3 rounded">
              <div className="text-xs text-gray-500">结构 ID</div>
              <div className="font-mono text-xs break-all">{result.structure_id || '-'}</div>
            </div>
            <div className="bg-gray-50 p-3 rounded">
              <div className="text-xs text-gray-500">序列长度</div>
              <div className="text-sm font-medium">{sequence.length} 残基</div>
            </div>
          </div>

          {/* Protenix 复合物信息卡片 */}
          {usedProtenix && (
            <div className="grid grid-cols-2 md:grid-cols-3 gap-3">
              <div className="bg-gradient-to-br from-emerald-50 to-teal-50 p-3 rounded border border-emerald-100">
                <div className="text-xs text-gray-500 flex items-center gap-1">
                  <Pill className="w-3 h-3" />
                  配体原子数
                </div>
                <div className="text-lg font-bold text-emerald-700">
                  {ligandCoords?.length ?? 0}
                </div>
                <div className="text-[10px] text-gray-500 mt-1">
                  {ligandSmiles ? `SMILES: ${ligandSmiles.slice(0, 24)}${ligandSmiles.length > 24 ? '...' : ''}` : '-'}
                </div>
              </div>
              <div className="bg-gradient-to-br from-orange-50 to-amber-50 p-3 rounded border border-orange-100">
                <div className="text-xs text-gray-500 flex items-center gap-1">
                  <TargetIcon className="w-3 h-3" />
                  结合位点残基
                </div>
                <div className="text-lg font-bold text-orange-700">
                  {bindingSite?.length ?? 0}
                </div>
                <div className="text-[10px] text-gray-500 mt-1">
                  {bindingSite && bindingSite.length > 0
                    ? `残基序号: ${bindingSite.slice(0, 8).join(', ')}${bindingSite.length > 8 ? ' ...' : ''}`
                    : '未识别'}
                </div>
              </div>
              <div className="bg-gray-50 p-3 rounded">
                <div className="text-xs text-gray-500">模型</div>
                <div className="text-sm font-medium">{result.model_name || 'protenix_v1'}</div>
                {result.duration_sec != null && (
                  <div className="text-[10px] text-gray-500 mt-1">耗时 {result.duration_sec}s</div>
                )}
              </div>
            </div>
          )}

          {/* 3D 可视化 — AlphaFold 风格 + 结合位点高亮 */}
          {pdbText && (
            <div>
              <h3 className="text-sm font-semibold mb-2 flex items-center gap-2">
                <Box className="w-4 h-4 text-primary-600" />
                3D 结构可视化（3Dmol.js · AlphaFold 风格按 pLDDT 着色
                {usedProtenix ? ' · 含配体与结合位点' : ''}）
              </h3>
              <ProteinStructure3D
                pdbText={pdbText}
                plddtMean={plddtMean}
                style="cartoon"
                height={520}
                spin
                bindingSiteResidues={bindingSite}
                showLigand={usedProtenix}
                showBindingSite={usedProtenix}
              />
            </div>
          )}

          {/* PDB 文本（折叠） */}
          {pdbText && (
            <details>
              <summary className="text-sm text-primary-600 cursor-pointer hover:text-primary-700">
                查看 PDB 文本（{pdbText.length} 字节）
              </summary>
              <pre className="mt-2 p-2 bg-slate-50 text-xs font-mono max-h-64 overflow-auto">
                {pdbText.slice(0, 3000)}
                {pdbText.length > 3000 ? '\n... (仅显示前 3000 字节，点击下载查看完整文件)' : ''}
              </pre>
            </details>
          )}
        </div>
      )}
    </div>
  );
}
