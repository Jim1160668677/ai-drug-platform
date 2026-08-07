'use client';

import { useState } from 'react';
import { planSynthesis, FEASIBILITY_LABELS, FEASIBILITY_COLORS, type SynthesisPlanResult } from '@/lib/api';
import { Beaker, Loader2, AlertCircle, CheckCircle2, AlertTriangle } from 'lucide-react';

export default function SynthesisPage() {
  const [smiles, setSmiles] = useState('CC(=O)Oc1ccccc1C(=O)O');
  const [scale, setScale] = useState(10);
  const [maxRoutes, setMaxRoutes] = useState(5);
  const [loading, setLoading] = useState(false);
  const [result, setResult] = useState<SynthesisPlanResult | null>(null);
  const [error, setError] = useState<string | null>(null);

  const handlePlan = async () => {
    if (!smiles.trim()) return;
    setLoading(true);
    setError(null);
    try {
      const r = await planSynthesis({
        smiles: smiles.trim(),
        max_routes: maxRoutes,
        target_scale_grams: scale,
      });
      setResult(r);
    } catch (e: unknown) {
      const err = e as { response?: { data?: { detail?: string } }; message?: string };
      setError(err.response?.data?.detail || err.message || '合成规划失败');
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="space-y-4">
      <div>
        <h1 className="text-2xl font-bold flex items-center gap-2">
          <Beaker className="w-6 h-6 text-primary-600" />
          合成规划
        </h1>
        <p className="text-sm text-slate-500 mt-1">
          集成 AiZynthFinder + SAscore + SCScore — 路线生成 / 可行性预测 / 成本估算一站式
        </p>
      </div>

      <div className="bg-white border rounded-lg p-4 space-y-3">
        <div>
          <label className="text-sm font-medium">目标分子 SMILES</label>
          <input
            value={smiles}
            onChange={(e) => setSmiles(e.target.value)}
            className="w-full px-3 py-2 border rounded font-mono text-sm"
          />
        </div>
        <div className="grid grid-cols-2 gap-3">
          <div>
            <label className="text-sm font-medium">目标规模（克）: {scale}g</label>
            <input
              type="range"
              min="1"
              max="100"
              value={scale}
              onChange={(e) => setScale(Number(e.target.value))}
              className="w-full"
            />
          </div>
          <div>
            <label className="text-sm font-medium">最大路线数: {maxRoutes}</label>
            <input
              type="range"
              min="1"
              max="10"
              value={maxRoutes}
              onChange={(e) => setMaxRoutes(Number(e.target.value))}
              className="w-full"
            />
          </div>
        </div>
        <button
          onClick={handlePlan}
          disabled={!smiles.trim() || loading}
          className="flex items-center gap-2 px-4 py-2 bg-primary-600 text-white rounded hover:bg-primary-700 disabled:opacity-50"
        >
          {loading && <Loader2 className="w-4 h-4 animate-spin" />}
          {loading ? '规划中...' : '生成合成规划'}
        </button>
      </div>

      {error && (
        <div className="flex items-center gap-2 px-3 py-2 bg-red-50 text-red-700 border border-red-200 rounded text-sm">
          <AlertCircle className="w-4 h-4" />
          {error}
        </div>
      )}

      {result && (
        <div className="space-y-3">
          {/* 可行性卡片 */}
          {result.feasibility_label && (
            <div className="bg-white border rounded-lg p-4">
              <div className="flex items-center justify-between">
                <div>
                  <div className="text-sm text-slate-500">可行性评估</div>
                  <span
                    className={`inline-block mt-1 px-2 py-0.5 text-xs rounded border ${
                      FEASIBILITY_COLORS[result.feasibility_label]
                    }`}
                  >
                    {FEASIBILITY_LABELS[result.feasibility_label]}
                  </span>
                </div>
                <div className="text-right text-sm">
                  <div>SAscore: <span className="font-mono">{result.sa_score?.toFixed(2)}</span></div>
                  <div>SCScore: <span className="font-mono">{result.sc_score?.toFixed(2) ?? '-'}</span></div>
                </div>
              </div>
            </div>
          )}

          {/* 成本卡片 */}
          {result.total_cost_usd != null && (
            <div className="bg-white border rounded-lg p-4">
              <h3 className="font-semibold mb-2">成本估算（{result.cost_breakdown?.target_scale_grams ?? scale}g 规模）</h3>
              <div className="grid grid-cols-2 gap-3 text-sm">
                <div>
                  <div className="text-slate-500">总成本</div>
                  <div className="text-xl font-bold text-primary-700">${result.total_cost_usd.toFixed(2)}</div>
                </div>
                <div>
                  <div className="text-slate-500">单克成本</div>
                  <div className="text-xl font-bold">${result.cost_per_gram?.toFixed(2) ?? '-'}</div>
                </div>
              </div>
              {result.cost_breakdown && (
                <div className="mt-3 space-y-1">
                  {(['materials', 'labor', 'equipment', 'overhead'] as const).map((k) => {
                    const v = result.cost_breakdown?.[k];
                    const max = Math.max(
                      result.cost_breakdown?.materials ?? 0,
                      result.cost_breakdown?.labor ?? 0,
                      result.cost_breakdown?.equipment ?? 0,
                      result.cost_breakdown?.overhead ?? 0,
                      1
                    );
                    const pct = max > 0 ? Math.min(100, ((v ?? 0) / max) * 100) : 0;
                    return (
                      <div key={k} className="text-xs">
                        <div className="flex justify-between">
                          <span>{k}</span>
                          <span className="font-mono">${(v ?? 0).toFixed(2)}</span>
                        </div>
                        <div className="h-2 bg-slate-200 rounded">
                          <div className="h-full bg-primary-400 rounded" style={{ width: `${pct}%` }} />
                        </div>
                      </div>
                    );
                  })}
                </div>
              )}
              {result.is_cost_effective === false && (
                <div className="flex items-center gap-2 mt-2 text-xs text-amber-700">
                  <AlertTriangle className="w-3 h-3" />
                  {result.warning || '成本偏高'}
                </div>
              )}
            </div>
          )}

          {/* 路线展示 */}
          {result.routes && result.routes.length > 0 && (
            <div className="bg-white border rounded-lg p-4">
              <h3 className="font-semibold mb-2">合成路线（共 {result.n_routes} 条）</h3>
              <div className="space-y-2">
                {result.routes.slice(0, 3).map((route, idx) => (
                  <div key={idx} className="border-l-2 border-primary-400 pl-3">
                    <div className="text-xs text-slate-500">
                      路线 {idx + 1}（{route.n_steps ?? route.steps?.length ?? 0} 步）
                    </div>
                    <ol className="mt-1 text-sm space-y-1">
                      {(route.steps || []).map((step, i) => (
                        <li key={i} className="flex gap-2">
                          <span className="font-mono text-xs text-primary-600">{step.step}.</span>
                          <span>{step.reaction}</span>
                        </li>
                      ))}
                    </ol>
                  </div>
                ))}
              </div>
            </div>
          )}

          {/* LLM 推荐 */}
          {result.recommendation && (
            <div className="bg-primary-50 border border-primary-200 rounded-lg p-4">
              <h3 className="font-semibold flex items-center gap-2 text-primary-800">
                <CheckCircle2 className="w-4 h-4" />
                AI 合成推荐
              </h3>
              <div className="mt-2 text-sm whitespace-pre-wrap">{result.recommendation}</div>
              {result.risk_assessment && (
                <div className="mt-2 text-xs text-amber-700">⚠ {result.risk_assessment}</div>
              )}
            </div>
          )}
        </div>
      )}
    </div>
  );
}
