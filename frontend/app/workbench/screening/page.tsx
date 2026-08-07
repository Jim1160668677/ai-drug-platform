'use client';

import { useState, useEffect } from 'react';
import { useQuery } from '@tanstack/react-query';
import { dualContextScreen, designVaccine } from '@/lib/api';
import { getTargets, getMolecules } from '@/lib/api';
import { Filter, Loader2, AlertCircle, Zap, Target as TargetIcon, Dna, Sparkles, ChevronDown, ChevronUp, Atom } from 'lucide-react';
import TargetSelect from '@/components/TargetSelect';
import MoleculeStructure from '@/components/molecules/MoleculeStructure';
import SequenceInput from '@/components/sequence/SequenceInput';
import { useAppStore } from '@/lib/store';
import AIInsightBanner from '@/components/coscientist/AIInsightBanner';

type Mode = 'screen' | 'vaccine';

type ScreenResult = {
  contexts?: string[];
  results?: Array<{
    smiles: string;
    efficacy_active: number;
    efficacy_neutral: number;
    conditional_amplification_score: number;
    is_amplifier: boolean;
  }>;
  amplifiers?: Array<{ smiles: string; score: number; mechanism?: string }>;
  summary?: string;
  n_amplifiers?: number;
  n_total?: number;
  threshold?: number;
  source?: string;
  target_id?: string;
  target_gene?: string;
} | null;

type VaccineResult = {
  structure?: any;
  neoantigens?: any[];
  vaccine?: { mrna_sequence?: string; gc_content?: number; length?: number; immunogenicity_score?: number; notes?: string; [k: string]: any };
  cost_usd?: number;
  duration_sec?: number;
  steps_completed?: number;
  [k: string]: any;
} | null;

export default function ScreeningPage() {
  const { currentProject } = useAppStore();
  const [mode, setMode] = useState<Mode>('screen');
  const [smilesInput, setSmilesInput] = useState('CCO\nCCN\nc1ccccc1');
  const [targetId, setTargetId] = useState('');
  const [mutationSeq, setMutationSeq] = useState('');
  const [contexts, setContexts] = useState<string>('immune_active,neutral');
  const [loading, setLoading] = useState(false);
  const [result, setResult] = useState<ScreenResult>(null);
  const [error, setError] = useState<string | null>(null);
  const [showMoleculePicker, setShowMoleculePicker] = useState(false);

  // 加载靶点对应的分子列表（用于双上下文筛选自动填充）
  const { data: moleculesData, isLoading: moleculesLoading } = useQuery({
    queryKey: ['molecules-for-screening', targetId],
    queryFn: () => getMolecules(targetId || undefined),
    enabled: !!targetId,
  });
  const targetMolecules = (((moleculesData as any)?.data ?? (moleculesData as any)?.items) || (Array.isArray(moleculesData) ? moleculesData : []) || []) as any[];

  // 加载靶点信息（用于自动填充突变序列）
  const { data: targetsData } = useQuery({
    queryKey: ['targets-for-screening'],
    queryFn: () => getTargets(),
  });
  const selectedTargetInfo = (((targetsData as any)?.data ?? (targetsData as any)?.items) || (Array.isArray(targetsData) ? targetsData : []) || []).find(
    (t: any) => t.id === targetId
  ) as any;

  // 选择靶点后：自动填充突变序列 + 弹出分子列表
  useEffect(() => {
    if (!targetId || !selectedTargetInfo) return;
    const variantInfo = selectedTargetInfo.variant_info || {};
    const candidateSeq = variantInfo.mutation_sequence || variantInfo.protein_sequence || '';
    if (candidateSeq && !mutationSeq) setMutationSeq(candidateSeq);
    if (targetMolecules.length > 0) setShowMoleculePicker(true);
  }, [targetId, selectedTargetInfo?.id]);

  // 从分子列表中选择分子，自动填充 SMILES
  const handlePickMolecule = (mol: any) => {
    const existingLines = smilesInput.split('\n').filter(Boolean);
    const newLine = mol.smiles || '';
    if (!existingLines.includes(newLine)) {
      setSmilesInput(prev => prev ? `${prev}\n${newLine}` : newLine);
    }
    setShowMoleculePicker(false);
  };

  const handleScreen = async () => {
    if (!targetId.trim()) return;
    setLoading(true);
    setError(null);
    try {
      const input: any = {
        target_id: targetId.trim(),
        contexts: contexts.split(',').map((c: string) => c.trim()).filter(Boolean),
      };
      if (mutationSeq.trim()) input.mutation_sequence = mutationSeq.trim();
      const r = await dualContextScreen(input);
      setResult(r);
    } catch (e: unknown) {
      const err = e as { response?: { data?: { detail?: string; message?: string } }; message?: string };
      setError(err.response?.data?.detail || err.response?.data?.message || err.message || '筛选失败');
    } finally {
      setLoading(false);
    }
  };

  const handleDesignVaccine = async () => {
    if (!mutationSeq.trim()) return;
    setLoading(true);
    setError(null);
    try {
      const r = await designVaccine({ sequence: mutationSeq.trim() });
      setResult(r as any);
    } catch (e: unknown) {
      const err = e as { response?: { data?: { detail?: string; message?: string } }; message?: string };
      setError(err.response?.data?.detail || err.response?.data?.message || err.message || '疫苗设计失败');
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="space-y-4">
      <div>
        <h1 className="text-2xl font-bold flex items-center gap-2">
          <Filter className="w-6 h-6 text-primary-600" />
          双上下文筛选 & mRNA 疫苗设计
        </h1>
        <p className="text-sm text-slate-500 mt-1">
          基于免疫微环境上下文（如 immune_active / neutral）的分子筛选 + 突变蛋白序列的 mRNA 疫苗设计
        </p>
      </div>

      <AIInsightBanner entityType="screening" projectId={currentProject?.id} />

      {/* 模式切换 */}
      <div className="flex items-center gap-2">
        <button
          onClick={() => setMode('screen')}
          className={`px-3 py-1.5 text-sm rounded border ${
            mode === 'screen'
              ? 'bg-primary-600 text-white border-primary-600'
              : 'bg-white text-gray-700 border-gray-300 hover:border-primary-400'
          }`}
        >
          双上下文筛选
        </button>
        <button
          onClick={() => setMode('vaccine')}
          className={`px-3 py-1.5 text-sm rounded border ${
            mode === 'vaccine'
              ? 'bg-primary-600 text-white border-primary-600'
              : 'bg-white text-gray-700 border-gray-300 hover:border-primary-400'
          }`}
        >
          mRNA 疫苗设计
        </button>
      </div>

      {mode === 'screen' ? (
        <div className="bg-white border rounded-lg p-4 space-y-3">
          {/* 靶点选择 */}
          <div>
            <label className="text-sm font-medium flex items-center gap-1">
              <TargetIcon className="w-3.5 h-3.5" />
              靶点（选择后自动关联突变序列与分子库）
            </label>
            <div className="mt-1">
              <TargetSelect
                value={targetId}
                onChange={setTargetId}
                projectId={currentProject?.id}
                placeholder="选择已发现的靶点"
              />
            </div>
            {selectedTargetInfo && (
              <div className="mt-2 p-2 bg-blue-50 border border-blue-100 rounded text-xs text-blue-800">
                <strong>{selectedTargetInfo.gene_symbol}</strong>
                {selectedTargetInfo.gene_name ? ` · ${selectedTargetInfo.gene_name}` : ''}
                {selectedTargetInfo.confidence_score != null && ` · 置信度 ${(selectedTargetInfo.confidence_score * 100).toFixed(1)}%`}
              </div>
            )}
          </div>

          {/* 分子选择器 */}
          {targetId && targetMolecules.length > 0 && (
            <div className="border border-blue-200 rounded-lg bg-blue-50/30 overflow-hidden">
              <button
                onClick={() => setShowMoleculePicker((s) => !s)}
                className="w-full px-3 py-2 text-left flex items-center justify-between text-sm font-medium text-blue-800 hover:bg-blue-50"
              >
                <span className="flex items-center gap-2">
                  <Atom className="w-4 h-4" />
                  从该靶点关联分子库选择（共 {targetMolecules.length} 个）
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
                          className="flex gap-2 p-2 bg-white border rounded text-left hover:border-primary-400 hover:bg-primary-50 transition-colors"
                        >
                          {mol.smiles && (
                            <div className="shrink-0">
                              <MoleculeStructure smiles={mol.smiles} width={60} height={50} />
                            </div>
                          )}
                          <div className="flex-1 min-w-0">
                            <div className="text-xs font-medium text-gray-800 truncate">{mol.name || '未命名分子'}</div>
                            <div className="font-mono text-[10px] text-gray-500 break-all">{mol.smiles?.slice(0, 30)}{mol.smiles?.length > 30 ? '...' : ''}</div>
                          </div>
                        </button>
                      ))}
                    </div>
                  )}
                </div>
              )}
            </div>
          )}

          {/* SMILES 输入 */}
          <div>
            <label className="text-sm font-medium">SMILES 列表（每行一个）</label>
            <textarea
              value={smilesInput}
              onChange={(e) => setSmilesInput(e.target.value)}
              placeholder="CCO&#10;CCN&#10;c1ccccc1"
              rows={4}
              className="w-full mt-1 px-3 py-2 border rounded font-mono text-sm"
            />
            <div className="text-xs text-gray-500 mt-1">
              也可从上方分子库批量选择
            </div>
          </div>

          {/* 上下文选择 */}
          <div>
            <label className="text-sm font-medium">上下文标签（逗号分隔）</label>
            <input
              value={contexts}
              onChange={(e) => setContexts(e.target.value)}
              placeholder="immune_active,neutral"
              className="w-full mt-1 px-3 py-2 border rounded text-sm"
            />
          </div>

          {/* 突变序列（mRNA 疫苗设计用） */}
          <div>
            <label className="text-sm font-medium flex items-center gap-1">
              <Dna className="w-3.5 h-3.5" />
              突变蛋白序列（可选 — 用于 mRNA 疫苗设计）
            </label>
            <div className="mt-1">
              <SequenceInput
                value={mutationSeq}
                onChange={setMutationSeq}
                placeholder="MKWVTIAVLCLAVL..."
                rows={3}
              />
            </div>
            {selectedTargetInfo && !mutationSeq && (
              <div className="mt-1 text-xs text-blue-600">
                可从靶点信息自动填充
              </div>
            )}
          </div>

          <button
            onClick={handleScreen}
            disabled={!targetId.trim() || loading}
            className="flex items-center gap-2 px-4 py-2 bg-primary-600 text-white rounded hover:bg-primary-700 disabled:opacity-50"
          >
            {loading && <Loader2 className="w-4 h-4 animate-spin" />}
            {loading ? '筛选中...' : '开始筛选'}
          </button>
        </div>
      ) : (
        <div className="bg-white border rounded-lg p-4 space-y-3">
          <AIInsightBanner entityType="vaccine" projectId={currentProject?.id} />
          <div className="text-sm font-medium flex items-center gap-1">
            <Dna className="w-4 h-4 text-purple-600" />
            mRNA 疫苗设计
          </div>
          <div className="bg-purple-50 border border-purple-200 rounded p-3 text-xs text-purple-800">
            输入突变蛋白序列，系统将生成 mRNA 疫苗候选序列，包含 GC 含量优化、Kozak 序列添加、poly-A tail 等。
          </div>
          <div>
            <label className="text-sm font-medium">突变蛋白序列 *</label>
            <div className="mt-1">
              <SequenceInput
                value={mutationSeq}
                onChange={setMutationSeq}
                placeholder="MKWVTIAVLCLAVL..."
                rows={5}
              />
            </div>
          </div>
          <button
            onClick={handleDesignVaccine}
            disabled={!mutationSeq.trim() || loading}
            className="flex items-center gap-2 px-4 py-2 bg-purple-600 text-white rounded hover:bg-purple-700 disabled:opacity-50"
          >
            {loading && <Loader2 className="w-4 h-4 animate-spin" />}
            {loading ? '设计中...' : '设计疫苗'}
          </button>
        </div>
      )}

      {error && (
        <div className="flex items-start gap-2 px-3 py-2 bg-red-50 text-red-700 border border-red-200 rounded text-sm">
          <AlertCircle className="w-4 h-4 mt-0.5 shrink-0" />
          <div>{error}</div>
        </div>
      )}

      {/* 结果展示 */}
      {result && (
        <div className="bg-white border rounded-lg p-4 space-y-4">
          <h3 className="font-semibold flex items-center gap-2">
            <Zap className="w-4 h-4 text-green-600" />
            筛选结果
          </h3>

          {result.n_amplifiers != null && (
            <div className="grid grid-cols-3 gap-3">
              <div className="bg-gradient-to-br from-blue-50 to-cyan-50 p-3 rounded border border-blue-100">
                <div className="text-xs text-gray-500">总分子数</div>
                <div className="text-xl font-bold text-blue-700">{result.n_total}</div>
              </div>
              <div className="bg-gradient-to-br from-green-50 to-emerald-50 p-3 rounded border border-green-100">
                <div className="text-xs text-gray-500">放大器数量</div>
                <div className="text-xl font-bold text-green-700">{result.n_amplifiers}</div>
              </div>
              <div className="bg-gray-50 p-3 rounded">
                <div className="text-xs text-gray-500">阈值</div>
                <div className="text-xl font-bold text-gray-700">{result.threshold != null ? result.threshold.toFixed(2) : '-'}</div>
              </div>
            </div>
          )}

          {/* 放大器列表 */}
          {result.amplifiers && result.amplifiers.length > 0 && (
            <div>
              <h4 className="text-sm font-medium text-gray-700 mb-2">
                条件放大器（{result.amplifiers.length} 个）
              </h4>
              <div className="overflow-x-auto">
                <table className="w-full text-sm">
                  <thead>
                    <tr className="border-b text-left text-gray-500">
                      <th className="pb-2">SMILES</th>
                      <th className="pb-2">Score</th>
                      <th className="pb-2">机制</th>
                    </tr>
                  </thead>
                  <tbody>
                    {result.amplifiers.slice(0, 10).map((a, i) => (
                      <tr key={i} className="border-b">
                        <td className="py-2 font-mono text-xs break-all">{a.smiles}</td>
                        <td className="py-2">
                          <Badge variant="green">{a.score?.toFixed(3)}</Badge>
                        </td>
                        <td className="py-2 text-xs text-gray-600">{a.mechanism || '-'}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </div>
          )}

          {/* 疫苗设计结果 */}
          {result.vaccine && (
            <div className="bg-gradient-to-br from-purple-50 to-pink-50 border border-purple-200 rounded-lg p-4 space-y-3">
              <h4 className="font-semibold flex items-center gap-2">
                <Sparkles className="w-4 h-4 text-purple-600" />
                mRNA 疫苗候选序列
              </h4>
              <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
                <div>
                  <div className="text-xs text-gray-500">mRNA 序列</div>
                  <div className="text-xs font-mono bg-white p-2 rounded mt-1 break-all max-h-20 overflow-auto">
                    {result.vaccine.mrna_sequence || '-'}
                  </div>
                </div>
                <div>
                  <div className="text-xs text-gray-500">GC 含量</div>
                  <div className="text-lg font-bold text-purple-700">
                    {result.vaccine.gc_content != null ? `${(result.vaccine.gc_content * 100).toFixed(1)}%` : '-'}
                  </div>
                </div>
                <div>
                  <div className="text-xs text-gray-500">长度</div>
                  <div className="text-lg font-bold text-purple-700">{result.vaccine.length || '-'}</div>
                </div>
                <div>
                  <div className="text-xs text-gray-500">免疫原性评分</div>
                  <div className="text-lg font-bold text-purple-700">
                    {result.vaccine.immunogenicity_score != null ? result.vaccine.immunogenicity_score.toFixed(3) : '-'}
                  </div>
                </div>
              </div>
              {result.vaccine.notes && (
                <div className="text-xs text-gray-600 bg-white/60 p-2 rounded">{result.vaccine.notes}</div>
              )}
            </div>
          )}

          {/* 摘要 */}
          {result.summary && (
            <div className="bg-gray-50 p-3 rounded text-xs text-gray-700 whitespace-pre-wrap">
              {result.summary}
            </div>
          )}
        </div>
      )}
    </div>
  );
}

function Badge({ variant, value }: { variant: string; value: string }) {
  const colors: Record<string, string> = {
    green: 'bg-green-100 text-green-700',
    blue: 'bg-blue-100 text-blue-700',
    yellow: 'bg-yellow-100 text-yellow-700',
    red: 'bg-red-100 text-red-700',
    gray: 'bg-gray-100 text-gray-700',
    status: 'bg-gray-100 text-gray-700',
    evidence: 'bg-purple-100 text-purple-700',
  };
  return (
    <span className={`px-2 py-0.5 rounded text-xs font-medium ${colors[variant] || colors.gray}`}>
      {value}
    </span>
  );
}
