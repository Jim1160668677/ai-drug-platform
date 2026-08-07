'use client';

import { useMemo } from 'react';
import { Activity, AlertTriangle, Shield, TrendingUp } from 'lucide-react';
import PlotlyChart from '@/components/charts/PlotlyChart';
import Badge from '@/components/ui/Badge';

interface RiskScoreChartProps {
  /** 风险评估对象 */
  assessment?: any;
  /** 已匹配位点列表（用于构建雷达图） */
  matches?: any[];
  /** 是否加载中 */
  loading?: boolean;
}

const RISK_CONFIG: Record<
  string,
  { label: string; color: string; bg: string; border: string; icon: typeof Activity; description: string }
> = {
  LOW: {
    label: '低风险',
    color: 'text-green-700',
    bg: 'bg-green-50',
    border: 'border-green-200',
    icon: Shield,
    description: '遗传风险较低，建议保持健康生活方式',
  },
  MODERATE: {
    label: '中等风险',
    color: 'text-yellow-700',
    bg: 'bg-yellow-50',
    border: 'border-yellow-200',
    icon: Activity,
    description: '存在一定遗传风险，建议关注相关因素',
  },
  HIGH: {
    label: '高风险',
    color: 'text-orange-700',
    bg: 'bg-orange-50',
    border: 'border-orange-200',
    icon: AlertTriangle,
    description: '遗传风险较高，建议针对性预防',
  },
  VERY_HIGH: {
    label: '极高风险',
    color: 'text-red-700',
    bg: 'bg-red-50',
    border: 'border-red-200',
    icon: AlertTriangle,
    description: '遗传风险极高，建议咨询专业医生',
  },
};

export default function RiskScoreChart({
  assessment,
  matches = [],
  loading,
}: RiskScoreChartProps) {
  const riskLevel: string = assessment?.risk_level || 'LOW';
  const overallScore: number = assessment?.overall_risk_score ?? 0;
  const cfg = RISK_CONFIG[riskLevel] || RISK_CONFIG.LOW;
  const Icon = cfg.icon;

  const radarData = useMemo(() => {
    if (!matches || matches.length === 0) return null;
    // 取风险位点的前 8 个构建雷达图
    const riskLoci = matches
      .filter((m) => m.is_risk)
      .slice(0, 8)
      .map((m) => ({
        rsid: m.locus?.rsid || m.snp_locus_id || '—',
        score: m.risk_score || 0,
      }));
    if (riskLoci.length === 0) return null;

    return [
      {
        type: 'scatterpolar',
        r: [...riskLoci.map((r) => r.score), riskLoci[0].score],
        theta: [...riskLoci.map((r) => r.rsid), riskLoci[0].rsid],
        fill: 'toself',
        fillcolor: 'rgba(220, 38, 38, 0.2)',
        line: { color: 'rgb(220, 38, 38)', width: 2 },
        name: '风险评分',
      },
    ];
  }, [matches]);

  if (loading) {
    return (
      <div className="space-y-3">
        <div className="h-20 w-full animate-pulse rounded bg-gray-100" />
        <div className="h-64 w-full animate-pulse rounded bg-gray-100" />
      </div>
    );
  }

  if (!assessment) {
    return (
      <div className="rounded-lg border border-dashed border-gray-300 bg-gray-50 p-6 text-center text-sm text-gray-500">
        <Activity className="w-10 h-10 mx-auto mb-2 text-gray-400" />
        暂无风险评估结果，请先完成 AI 分析步骤
      </div>
    );
  }

  return (
    <div className="space-y-4">
      {/* 风险等级展示卡 */}
      <div className={`rounded-lg border p-4 ${cfg.bg} ${cfg.border}`}>
        <div className="flex items-center justify-between flex-wrap gap-3">
          <div className="flex items-center gap-3">
            <Icon className={`w-8 h-8 ${cfg.color}`} />
            <div>
              <div className="text-xs text-gray-600">综合风险等级</div>
              <div className={`text-2xl font-bold ${cfg.color}`}>
                {cfg.label}
              </div>
            </div>
          </div>
          <div className="flex items-center gap-4">
            <div className="text-right">
              <div className="text-xs text-gray-600">综合评分</div>
              <div className={`text-2xl font-bold ${cfg.color}`}>
                {(overallScore * 100).toFixed(1)}%
              </div>
            </div>
            <div className="text-right">
              <div className="text-xs text-gray-600">核心位点</div>
              <div className="text-lg font-semibold text-gray-900">
                {assessment.core_loci_matched ?? 0}
              </div>
            </div>
            <div className="text-right">
              <div className="text-xs text-gray-600">辅助位点</div>
              <div className="text-lg font-semibold text-gray-900">
                {assessment.auxiliary_loci_matched ?? 0}
              </div>
            </div>
          </div>
        </div>
        <div className="mt-3 text-xs text-gray-700">{cfg.description}</div>
        <div className="mt-2 h-2 w-full bg-white/60 rounded-full overflow-hidden">
          <div
            className={`h-full transition-all duration-500 ${
              riskLevel === 'VERY_HIGH'
                ? 'bg-red-500'
                : riskLevel === 'HIGH'
                  ? 'bg-orange-500'
                  : riskLevel === 'MODERATE'
                    ? 'bg-yellow-500'
                    : 'bg-green-500'
            }`}
            style={{ width: `${Math.max(5, Math.min(100, overallScore * 100))}%` }}
          />
        </div>
      </div>

      {/* 雷达图（若有风险位点） */}
      {radarData && (
        <div className="rounded-lg border border-gray-200 bg-white p-4">
          <div className="flex items-center gap-2 mb-3">
            <TrendingUp className="w-4 h-4 text-primary-600" />
            <span className="text-sm font-semibold text-gray-900">
              风险位点评分雷达图
            </span>
          </div>
          <div className="h-72">
            <PlotlyChart
              data={radarData}
              layout={{
                margin: { t: 20, b: 20, l: 40, r: 40 },
                polar: {
                  radialaxis: {
                    visible: true,
                    range: [0, 1],
                    tickformat: '.1f',
                  },
                },
                showlegend: false,
                paper_bgcolor: 'rgba(0,0,0,0)',
                plot_bgcolor: 'rgba(0,0,0,0)',
              }}
              config={{ displayModeBar: false, responsive: true }}
            />
          </div>
        </div>
      )}
    </div>
  );
}
