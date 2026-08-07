'use client';

import { useState, useMemo, useCallback } from 'react';
import {
  predictPerturbation,
  annotateCells,
  listCellEngines,
  type PerturbationResult,
} from '@/lib/api';
import { parseGeneList } from '@/lib/utils/geneListParser';
import GeneFileImport from '@/components/cells/GeneFileImport';
import { Microscope, Loader2, AlertCircle, CheckCircle2, Table2 } from 'lucide-react';

type Tab = 'perturbation' | 'annotation' | 'engines';

export default function CellsPage() {
  const [tab, setTab] = useState<Tab>('perturbation');
  const [geneInput, setGeneInput] = useState('');
  const [loading, setLoading] = useState(false);
  const [results, setResults] = useState<PerturbationResult[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [progress, setProgress] = useState({ done: 0, total: 0 });
  const [enginesResult, setEnginesResult] = useState<unknown>(null);

  // 实时解析基因列表
  const parsedGenes = useMemo(() => parseGeneList(geneInput), [geneInput]);

  const handleBatchPerturbation = useCallback(async () => {
    if (parsedGenes.genes.length === 0) return;
    setLoading(true);
    setError(null);
    setResults([]);
    setProgress({ done: 0, total: parsedGenes.genes.length });

    const collected: PerturbationResult[] = [];
    for (let i = 0; i < parsedGenes.genes.length; i++) {
      const gene = parsedGenes.genes[i];
      try {
        const r = (await predictPerturbation({ gene })) as PerturbationResult;
        collected.push(r);
      } catch (e: unknown) {
        const err = e as { response?: { data?: { detail?: string } }; message?: string };
        // 单基因失败不中断批量预测（容错）
        collected.push({
          gene,
          predicted_effect: '预测失败',
          confidence: 0,
          source: 'error',
          affected_pathways: [],
          // 附加错误信息（PerturbationResult 无 detail 字段，用 source 携带）
        } as PerturbationResult & { detail?: string });
        // 记录最后一个错误用于提示
        if (i === parsedGenes.genes.length - 1 && collected.every((c) => c.source === 'error')) {
          setError(err.response?.data?.detail || err.message || '批量预测失败');
        }
      } finally {
        setProgress({ done: i + 1, total: parsedGenes.genes.length });
      }
    }

    setResults(collected);
    setLoading(false);
  }, [parsedGenes.genes]);

  const handleEngines = async () => {
    setLoading(true);
    setError(null);
    try {
      const r = await listCellEngines();
      setEnginesResult(r);
    } catch (e: unknown) {
      const err = e as { response?: { data?: { detail?: string } }; message?: string };
      setError(err.response?.data?.detail || err.message || '查询失败');
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="space-y-4">
      <div>
        <h1 className="text-2xl font-bold flex items-center gap-2">
          <Microscope className="w-6 h-6 text-primary-600" />
          单细胞分析
        </h1>
        <p className="text-sm text-slate-500 mt-1">
          集成 scGPT — 基因扰动效应预测（支持批量）+ 细胞类型注释
        </p>
      </div>

      <div className="flex gap-2">
        {([
          { value: 'perturbation', label: '基因扰动' },
          { value: 'annotation', label: '细胞注释' },
          { value: 'engines', label: '引擎状态' },
        ] as const).map((t) => (
          <button
            key={t.value}
            onClick={() => {
              setTab(t.value);
              setError(null);
            }}
            className={`px-3 py-1.5 text-sm rounded ${
              tab === t.value ? 'bg-primary-600 text-white' : 'bg-white border'
            }`}
          >
            {t.label}
          </button>
        ))}
      </div>

      {tab === 'perturbation' && (
        <div className="bg-white border rounded-lg p-4 space-y-3">
          <label className="text-sm font-medium">基因符号列表（逗号或换行分隔）</label>
          <textarea
            value={geneInput}
            onChange={(e) => setGeneInput(e.target.value)}
            placeholder={'EGFR\nTP53\nBRCA1\nCD8A'}
            rows={5}
            className="w-full px-3 py-2 border rounded font-mono text-sm"
          />

          <GeneFileImport onGenesLoaded={(text) => setGeneInput(text)} />

          {/* 实时解析结果 */}
          {geneInput.trim() && (
            <div className="text-xs flex flex-wrap items-center gap-3">
              <span className="flex items-center gap-1 text-green-600">
                <CheckCircle2 className="w-3.5 h-3.5" />
                有效基因: {parsedGenes.genes.length}
              </span>
              {parsedGenes.invalid.length > 0 && (
                <span className="flex items-center gap-1 text-amber-600">
                  <AlertCircle className="w-3.5 h-3.5" />
                  无效: {parsedGenes.invalid.join(', ')}
                </span>
              )}
              {parsedGenes.genes.length > 0 && (
                <span className="text-gray-500">
                  已识别: {parsedGenes.genes.slice(0, 8).join(', ')}
                  {parsedGenes.genes.length > 8 && ` ...+${parsedGenes.genes.length - 8}`}
                </span>
              )}
            </div>
          )}

          <button
            onClick={handleBatchPerturbation}
            disabled={parsedGenes.genes.length === 0 || loading}
            className="flex items-center gap-2 px-4 py-2 bg-primary-600 text-white rounded hover:bg-primary-700 disabled:opacity-50"
          >
            {loading && <Loader2 className="w-4 h-4 animate-spin" />}
            {loading
              ? `预测中 (${progress.done}/${progress.total})...`
              : `批量预测扰动效应（${parsedGenes.genes.length} 个基因）`}
          </button>

          {/* 批量结果表格 */}
          {results.length > 0 && (
            <div className="border rounded-lg overflow-hidden">
              <div className="flex items-center gap-2 px-3 py-2 bg-gray-50 border-b text-sm font-medium">
                <Table2 className="w-4 h-4 text-primary-600" />
                预测结果（共 {results.length} 个基因）
              </div>
              <div className="overflow-x-auto max-h-96">
                <table className="w-full text-sm">
                  <thead className="sticky top-0 bg-white border-b">
                    <tr className="text-left text-gray-500 text-xs">
                      <th className="px-3 py-2">基因</th>
                      <th className="px-3 py-2">扰动效应</th>
                      <th className="px-3 py-2">方向</th>
                      <th className="px-3 py-2">置信度</th>
                      <th className="px-3 py-2">来源</th>
                    </tr>
                  </thead>
                  <tbody>
                    {results.map((r, i) => (
                      <tr key={i} className="border-b last:border-0 hover:bg-gray-50">
                        <td className="px-3 py-2 font-mono font-medium text-gray-800">
                          {r.gene}
                        </td>
                        <td className="px-3 py-2 text-gray-600">
                          {r.predicted_effect}
                        </td>
                        <td className="px-3 py-2">
                          {(r as any).direction ? (
                            <span
                              className={`px-1.5 py-0.5 rounded text-xs ${
                                (r as any).direction === 'up'
                                  ? 'bg-red-100 text-red-700'
                                  : (r as any).direction === 'down'
                                    ? 'bg-blue-100 text-blue-700'
                                    : 'bg-gray-100 text-gray-700'
                              }`}
                            >
                              {(r as any).direction}
                            </span>
                          ) : (
                            <span className="text-gray-400">—</span>
                          )}
                        </td>
                        <td className="px-3 py-2">
                          {r.confidence != null && r.confidence > 0 ? (
                            <div className="flex items-center gap-2">
                              <div className="w-12 h-1.5 bg-gray-100 rounded overflow-hidden">
                                <div
                                  className="h-full bg-primary-500"
                                  style={{ width: `${Math.min(100, r.confidence * 100)}%` }}
                                />
                              </div>
                              <span className="text-xs text-gray-600">
                                {(r.confidence * 100).toFixed(0)}%
                              </span>
                            </div>
                          ) : (
                            <span className="text-gray-400">—</span>
                          )}
                        </td>
                        <td className="px-3 py-2 text-xs text-gray-500 uppercase">
                          {r.source}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </div>
          )}
        </div>
      )}

      {tab === 'engines' && (
        <div className="bg-white border rounded-lg p-4 space-y-3">
          <button
            onClick={handleEngines}
            disabled={loading}
            className="flex items-center gap-2 px-4 py-2 bg-primary-600 text-white rounded hover:bg-primary-700 disabled:opacity-50"
          >
            {loading && <Loader2 className="w-4 h-4 animate-spin" />}
            查询引擎状态
          </button>
          {enginesResult && (
            <pre className="p-2 bg-slate-50 text-xs font-mono overflow-auto max-h-96 rounded">
              {JSON.stringify(enginesResult, null, 2)}
            </pre>
          )}
        </div>
      )}

      {tab === 'annotation' && (
        <div className="bg-white border rounded-lg p-4 space-y-3">
          <p className="text-sm text-slate-500">
            细胞注释需上传表达矩阵数据，请通过 API 调用。
          </p>
        </div>
      )}

      {error && (
        <div className="flex items-center gap-2 px-3 py-2 bg-red-50 text-red-700 border border-red-200 rounded text-sm">
          <AlertCircle className="w-4 h-4" />
          {error}
        </div>
      )}
    </div>
  );
}
