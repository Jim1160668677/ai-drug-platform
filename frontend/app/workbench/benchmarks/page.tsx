'use client';

import { useState } from 'react';
import { compareBenchmarks, runAllBenchmarks, BENCHMARK_CASES, type BenchmarkCompareResult } from '@/lib/api';
import { BarChart3, Loader2, AlertCircle, TrendingDown, Zap } from 'lucide-react';
import AIInsightBanner from '@/components/coscientist/AIInsightBanner';

export default function BenchmarksPage() {
  const [caseId, setCaseId] = useState('aspirin');
  const [loading, setLoading] = useState(false);
  const [loadingAll, setLoadingAll] = useState(false);
  const [result, setResult] = useState<BenchmarkCompareResult | null>(null);
  const [allResult, setAllResult] = useState<{ conclusion: string; summary: { hybrid_wins: number; avg_cost_saving_pct: number; avg_speedup_factor: number } } | null>(null);
  const [error, setError] = useState<string | null>(null);

  const handleCompare = async () => {
    const caseData = BENCHMARK_CASES.find((c) => c.case_id === caseId);
    if (!caseData) return;
    setLoading(true);
    setError(null);
    try {
      const r = await compareBenchmarks({
        case_id: caseId,
        smiles: caseData.smiles,
        target_gene: caseData.target_gene,
      });
      setResult(r);
    } catch (e: unknown) {
      const err = e as { response?: { data?: { detail?: string } }; message?: string };
      setError(err.response?.data?.detail || err.message || '基准评测失败');
    } finally {
      setLoading(false);
    }
  };

  const handleRunAll = async () => {
    setLoadingAll(true);
    setError(null);
    try {
      const r = await runAllBenchmarks();
      setAllResult(r);
    } catch (e: unknown) {
      const err = e as { response?: { data?: { detail?: string } }; message?: string };
      setError(err.response?.data?.detail || err.message || '批量评测失败');
    } finally {
      setLoadingAll(false);
    }
  };

  const renderModeBar = (label: string, value: number, maxValue: number, color: string) => {
    const pct = maxValue > 0 ? Math.min(100, (value / maxValue) * 100) : 0;
    return (
      <div className="space-y-1">
        <div className="flex justify-between text-xs">
          <span>{label}</span>
          <span className="font-mono">{value.toFixed(2)}</span>
        </div>
        <div className="h-3 bg-slate-200 rounded overflow-hidden">
          <div className={`h-full ${color}`} style={{ width: `${pct}%` }} />
        </div>
      </div>
    );
  };

  return (
    <div className="space-y-4">
      <div>
        <h1 className="text-2xl font-bold flex items-center gap-2">
          <BarChart3 className="w-6 h-6 text-primary-600" />
          基准评测
        </h1>
        <p className="text-sm text-slate-500 mt-1">
          对比 hybrid / traditional_supercompute / llm_only 三种模式的成本-精度优势
        </p>
      </div>

      <AIInsightBanner entityType="benchmark" />

      <div className="bg-white border rounded-lg p-4 space-y-3">
        <label className="text-sm font-medium">案例选择</label>
        <select
          value={caseId}
          onChange={(e) => setCaseId(e.target.value)}
          className="w-full px-3 py-2 border rounded text-sm"
        >
          {BENCHMARK_CASES.map((c) => (
            <option key={c.case_id} value={c.case_id}>
              {c.label}
            </option>
          ))}
        </select>
        <div className="flex gap-2">
          <button
            onClick={handleCompare}
            disabled={loading}
            className="flex items-center gap-2 px-4 py-2 bg-primary-600 text-white rounded hover:bg-primary-700 disabled:opacity-50"
          >
            {loading && <Loader2 className="w-4 h-4 animate-spin" />}
            对比 3 模式
          </button>
          <button
            onClick={handleRunAll}
            disabled={loadingAll}
            className="flex items-center gap-2 px-4 py-2 bg-slate-700 text-white rounded hover:bg-slate-800 disabled:opacity-50"
          >
            {loadingAll && <Loader2 className="w-4 h-4 animate-spin" />}
            跑全部 9 案例
          </button>
        </div>
      </div>

      {error && (
        <div className="flex items-center gap-2 px-3 py-2 bg-red-50 text-red-700 border border-red-200 rounded text-sm">
          <AlertCircle className="w-4 h-4" />
          {error}
        </div>
      )}

      {result?.comparison && (
        <div className="grid grid-cols-3 gap-3">
          <div className="bg-green-50 border border-green-200 rounded-lg p-3">
            <div className="flex items-center gap-2 text-green-800 text-sm font-medium">
              <TrendingDown className="w-4 h-4" />
              成本节省
            </div>
            <div className="text-2xl font-bold text-green-700">
              {result.comparison.cost_saving_pct.toFixed(1)}%
            </div>
          </div>
          <div className="bg-blue-50 border border-blue-200 rounded-lg p-3">
            <div className="text-blue-800 text-sm font-medium">加速比</div>
            <div className="text-2xl font-bold text-blue-700">
              {result.comparison.speedup_factor.toFixed(1)}×
            </div>
          </div>
          <div className="bg-amber-50 border border-amber-200 rounded-lg p-3">
            <div className="text-amber-800 text-sm font-medium">能耗节省</div>
            <div className="text-2xl font-bold text-amber-700">
              {result.comparison.energy_saving_pct.toFixed(1)}%
            </div>
          </div>
        </div>
      )}

      {result?.results && (
        <div className="bg-white border rounded-lg p-4 space-y-3">
          <h2 className="font-semibold">三模式对比</h2>
          {renderModeBar(
            'Hybrid 成本',
            result.results.hybrid.metrics.cost_usd,
            result.results.traditional_supercompute.metrics.cost_usd,
            'bg-primary-500'
          )}
          {renderModeBar(
            'Traditional 成本',
            result.results.traditional_supercompute.metrics.cost_usd,
            result.results.traditional_supercompute.metrics.cost_usd,
            'bg-red-500'
          )}
          {renderModeBar(
            'LLM-only 成本',
            result.results.llm_only.metrics.cost_usd,
            result.results.traditional_supercompute.metrics.cost_usd,
            'bg-amber-500'
          )}
          <div className="text-xs text-slate-500 pt-2 border-t">
            Winner: <span className="font-mono">{result.winner}</span>
          </div>
        </div>
      )}

      {allResult && (
        <div className="bg-white border rounded-lg p-4 space-y-3">
          <h2 className="font-semibold flex items-center gap-2">
            <Zap className="w-4 h-4 text-amber-500" />
            9 案例汇总
          </h2>
          <div className="grid grid-cols-3 gap-3 text-sm">
            <div>
              <div className="text-slate-500">Hybrid 胜出</div>
              <div className="text-2xl font-bold text-primary-700">{allResult.summary.hybrid_wins}/9</div>
            </div>
            <div>
              <div className="text-slate-500">平均成本节省</div>
              <div className="text-2xl font-bold text-green-700">
                {allResult.summary.avg_cost_saving_pct.toFixed(1)}%
              </div>
            </div>
            <div>
              <div className="text-slate-500">平均加速</div>
              <div className="text-2xl font-bold text-blue-700">
                {allResult.summary.avg_speedup_factor.toFixed(1)}×
              </div>
            </div>
          </div>
          <p className="text-sm text-slate-700 pt-2 border-t">{allResult.conclusion}</p>
        </div>
      )}
    </div>
  );
}
