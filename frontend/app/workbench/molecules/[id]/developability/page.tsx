'use client';

import { useState } from 'react';
import { useParams, useRouter } from 'next/navigation';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import {
  assessDevelopability,
  listDevelopability,
  RECOMMENDATION_LABELS,
  RECOMMENDATION_COLORS,
  SA_EASE_LABELS,
  TOXICITY_RISK_LABELS,
  type DevelopabilityAssessment,
} from '@/lib/api';
import { ArrowLeft, RefreshCw, AlertTriangle, CheckCircle, XCircle } from 'lucide-react';

// ========== 5 维度雷达图（SVG 简易实现，避免新依赖） ==========

function RadarChart({ assessment }: { assessment: DevelopabilityAssessment }) {
  // 5 个维度，归一化到 0-1（值越高越好）
  const dimensions = [
    {
      name: '合成可及性',
      value: assessment.sa_score != null ? 1 - (assessment.sa_score - 1) / 9 : 0.5,
      label: `${assessment.sa_score ?? '-'} (${SA_EASE_LABELS[assessment.sa_ease_label ?? 'medium'] ?? '-'})`,
    },
    {
      name: '毒理安全',
      value:
        assessment.toxicity_risk === 'low'
          ? 1.0
          : assessment.toxicity_risk === 'moderate'
            ? 0.5
            : 0.0,
      label: TOXICITY_RISK_LABELS[assessment.toxicity_risk ?? 'low'] ?? '-',
    },
    {
      name: '制剂递送',
      value: assessment.formulation_score ?? 0.5,
      label: `${((assessment.formulation_score ?? 0) * 100).toFixed(0)}%`,
    },
    {
      name: '成本可控',
      value:
        assessment.cost_estimate_usd != null
          ? Math.max(0, Math.min(1, 1 - (assessment.cost_estimate_usd - 500) / 4500))
          : 0.5,
      label: `$${assessment.cost_estimate_usd?.toFixed(0) ?? '-'}/g`,
    },
    {
      name: '综合评分',
      value: assessment.overall_score ?? 0.5,
      label: `${((assessment.overall_score ?? 0) * 100).toFixed(0)}%`,
    },
  ];

  const center = 120;
  const radius = 90;
  const angleStep = (Math.PI * 2) / dimensions.length;

  // 多边形顶点（归一化值）
  const points = dimensions.map((d, i) => {
    const angle = -Math.PI / 2 + i * angleStep;
    const r = radius * Math.max(0, Math.min(1, d.value));
    return {
      x: center + r * Math.cos(angle),
      y: center + r * Math.sin(angle),
      labelX: center + (radius + 20) * Math.cos(angle),
      labelY: center + (radius + 20) * Math.sin(angle),
      name: d.name,
      label: d.label,
    };
  });

  // 背景同心圆（4 层）
  const rings = [0.25, 0.5, 0.75, 1.0].map((scale) =>
    dimensions
      .map((_, i) => {
        const angle = -Math.PI / 2 + i * angleStep;
        const r = radius * scale;
        return `${center + r * Math.cos(angle)},${center + r * Math.sin(angle)}`;
      })
      .join(' ')
  );

  const polygonPoints = points.map((p) => `${p.x},${p.y}`).join(' ');

  return (
    <svg viewBox="0 0 280 280" className="w-full max-w-sm mx-auto">
      {/* 背景同心多边形 */}
      {rings.map((pts, i) => (
        <polygon
          key={i}
          points={pts}
          fill="none"
          stroke="#e2e8f0"
          strokeWidth="1"
        />
      ))}
      {/* 轴线 */}
      {points.map((p, i) => (
        <line
          key={i}
          x1={center}
          y1={center}
          x2={p.x}
          y2={p.y}
          stroke="#e2e8f0"
          strokeWidth="1"
        />
      ))}
      {/* 数据多边形 */}
      <polygon
        points={polygonPoints}
        fill="rgba(59, 130, 246, 0.2)"
        stroke="#3b82f6"
        strokeWidth="2"
      />
      {/* 数据点 */}
      {points.map((p, i) => (
        <circle key={i} cx={p.x} cy={p.y} r="3" fill="#3b82f6" />
      ))}
      {/* 维度标签 */}
      {points.map((p, i) => (
        <g key={i}>
          <text
            x={p.labelX}
            y={p.labelY - 4}
            textAnchor="middle"
            className="fill-slate-700 text-[10px] font-medium"
          >
            {p.name}
          </text>
          <text
            x={p.labelX}
            y={p.labelY + 8}
            textAnchor="middle"
            className="fill-slate-500 text-[9px]"
          >
            {p.label}
          </text>
        </g>
      ))}
    </svg>
  );
}

// ========== 主体页面 ==========

export default function DevelopabilityPage() {
  const params = useParams();
  const router = useRouter();
  const queryClient = useQueryClient();
  const moleculeId = params.id as string;

  const [selectedVersion, setSelectedVersion] = useState<number | null>(null);

  // 查询历史评估
  const { data: history = [], isLoading } = useQuery({
    queryKey: ['developability', moleculeId],
    queryFn: () => listDevelopability(moleculeId),
    enabled: !!moleculeId,
  });

  // 触发评估
  const assessMutation = useMutation({
    mutationFn: () => assessDevelopability(moleculeId),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['developability', moleculeId] });
    },
  });

  // 当前选中的评估（默认最新版本）
  const current =
    history.find((h) => h.version === selectedVersion) ?? history[0];

  return (
    <div className="space-y-6">
      {/* 顶部导航 */}
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-3">
          <button
            onClick={() => router.back()}
            className="p-2 rounded hover:bg-slate-100"
            aria-label="返回"
          >
            <ArrowLeft className="w-4 h-4" />
          </button>
          <div>
            <h1 className="text-xl font-bold">药物可开发性评估</h1>
            <p className="text-sm text-slate-500">
              分子 ID: {moleculeId?.slice(0, 8)}...
            </p>
          </div>
        </div>
        <button
          onClick={() => assessMutation.mutate()}
          disabled={assessMutation.isPending}
          className="flex items-center gap-2 px-4 py-2 bg-blue-600 text-white rounded hover:bg-blue-700 disabled:opacity-50"
        >
          <RefreshCw className={`w-4 h-4 ${assessMutation.isPending ? 'animate-spin' : ''}`} />
          {assessMutation.isPending ? '评估中...' : '触发评估'}
        </button>
      </div>

      {isLoading && <div className="text-center py-8 text-slate-400">加载中...</div>}

      {!isLoading && history.length === 0 && (
        <div className="text-center py-12 text-slate-400 border-2 border-dashed border-slate-200 rounded-lg">
          <AlertTriangle className="w-8 h-8 mx-auto mb-2 text-slate-300" />
          <p>暂无评估记录</p>
          <p className="text-xs mt-1">点击右上角"触发评估"开始第一次可开发性分析</p>
        </div>
      )}

      {current && (
        <>
          {/* 版本切换 */}
          {history.length > 1 && (
            <div className="flex items-center gap-2 flex-wrap">
              <span className="text-sm text-slate-500">历史版本：</span>
              {history.map((h) => (
                <button
                  key={h.version}
                  onClick={() => setSelectedVersion(h.version)}
                  className={`px-3 py-1 text-xs rounded border ${
                    current.version === h.version
                      ? 'bg-blue-600 text-white border-blue-600'
                      : 'bg-white text-slate-600 border-slate-300 hover:border-blue-400'
                  }`}
                >
                  v{h.version}
                </button>
              ))}
            </div>
          )}

          {/* 决策徽章 */}
          <div
            className={`flex items-center gap-3 p-4 border rounded-lg ${RECOMMENDATION_COLORS[current.recommendation]}`}
          >
            {current.recommendation === 'go' && <CheckCircle className="w-6 h-6" />}
            {current.recommendation === 'revise' && <AlertTriangle className="w-6 h-6" />}
            {current.recommendation === 'no_go' && <XCircle className="w-6 h-6" />}
            <div className="flex-1">
              <div className="font-bold text-lg">
                {RECOMMENDATION_LABELS[current.recommendation]}
              </div>
              <div className="text-sm opacity-90">{current.rationale}</div>
            </div>
            <div className="text-right">
              <div className="text-xs opacity-75">综合评分</div>
              <div className="text-2xl font-bold">
                {((current.overall_score ?? 0) * 100).toFixed(0)}%
              </div>
            </div>
          </div>

          <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
            {/* 雷达图 */}
            <div className="p-4 border rounded-lg">
              <h2 className="font-bold mb-2">5 维度雷达图</h2>
              <RadarChart assessment={current} />
            </div>

            {/* 明细表 */}
            <div className="space-y-4">
              {/* 5 维度明细 */}
              <div className="p-4 border rounded-lg">
                <h2 className="font-bold mb-3">维度明细</h2>
                <table className="w-full text-sm">
                  <tbody>
                    <tr className="border-b">
                      <td className="py-2 text-slate-500">合成可及性</td>
                      <td className="py-2 text-right font-mono">
                        {current.sa_score?.toFixed(2)} ({SA_EASE_LABELS[current.sa_ease_label ?? 'medium']})
                      </td>
                    </tr>
                    <tr className="border-b">
                      <td className="py-2 text-slate-500">毒理风险</td>
                      <td className="py-2 text-right">
                        <span
                          className={`px-2 py-0.5 rounded text-xs ${
                            current.toxicity_risk === 'low'
                              ? 'bg-green-100 text-green-700'
                              : current.toxicity_risk === 'moderate'
                                ? 'bg-yellow-100 text-yellow-700'
                                : 'bg-red-100 text-red-700'
                          }`}
                        >
                          {TOXICITY_RISK_LABELS[current.toxicity_risk ?? 'low']}
                        </span>
                      </td>
                    </tr>
                    <tr className="border-b">
                      <td className="py-2 text-slate-500">制剂递送</td>
                      <td className="py-2 text-right font-mono">
                        {((current.formulation_score ?? 0) * 100).toFixed(0)}%
                      </td>
                    </tr>
                    <tr className="border-b">
                      <td className="py-2 text-slate-500">生产成本</td>
                      <td className="py-2 text-right font-mono">
                        ${current.cost_estimate_usd?.toFixed(2)}/g
                      </td>
                    </tr>
                  </tbody>
                </table>
                {current.formulation_notes && (
                  <p className="text-xs text-slate-400 mt-2">{current.formulation_notes}</p>
                )}
              </div>

              {/* 毒理警示详情 */}
              {current.toxicity_alerts && current.toxicity_alerts.length > 0 && (
                <div className="p-4 border rounded-lg">
                  <h2 className="font-bold mb-2">毒理警示结构</h2>
                  <ul className="space-y-1">
                    {current.toxicity_alerts.map((a, i) => (
                      <li key={i} className="flex items-center justify-between text-sm">
                        <span className="font-mono text-xs">{a.name}</span>
                        <span
                          className={`px-2 py-0.5 rounded text-xs ${
                            a.severity === 'danger'
                              ? 'bg-red-100 text-red-700'
                              : 'bg-yellow-100 text-yellow-700'
                          }`}
                        >
                          {a.severity === 'danger' ? '高危' : '警告'}
                        </span>
                      </li>
                    ))}
                  </ul>
                </div>
              )}

              {/* 成本明细 */}
              <div className="p-4 border rounded-lg">
                <h2 className="font-bold mb-2">成本明细</h2>
                <table className="w-full text-sm">
                  <tbody>
                    <tr className="border-b">
                      <td className="py-1.5 text-slate-500">原料</td>
                      <td className="py-1.5 text-right font-mono">
                        ${current.cost_breakdown?.materials?.toFixed(2)}
                      </td>
                    </tr>
                    <tr className="border-b">
                      <td className="py-1.5 text-slate-500">人工</td>
                      <td className="py-1.5 text-right font-mono">
                        ${current.cost_breakdown?.labor?.toFixed(2)}
                      </td>
                    </tr>
                    <tr className="border-b">
                      <td className="py-1.5 text-slate-500">间接成本</td>
                      <td className="py-1.5 text-right font-mono">
                        ${current.cost_breakdown?.overhead?.toFixed(2)}
                      </td>
                    </tr>
                    <tr className="font-bold">
                      <td className="py-1.5">合计</td>
                      <td className="py-1.5 text-right font-mono">
                        ${current.cost_estimate_usd?.toFixed(2)}
                      </td>
                    </tr>
                  </tbody>
                </table>
              </div>
            </div>
          </div>

          <div className="text-xs text-slate-400 text-right">
            评估时间: {new Date(current.created_at).toLocaleString('zh-CN')} · 版本 v{current.version}
          </div>
        </>
      )}
    </div>
  );
}
