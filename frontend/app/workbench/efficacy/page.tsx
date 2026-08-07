'use client';

import { useState } from 'react';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import {
  Activity,
  TrendingUp,
  TrendingDown,
  AlertCircle,
  Info,
  CheckCircle2,
  XCircle,
  Clock,
  Heart,
  Plus,
  Calculator,
  LineChart,
  Loader2,
  X,
  Beaker,
} from 'lucide-react';
import {
  getEfficacySummary,
  recordOutcome,
  recordAdverseEvent,
  recistClassify,
  kaplanMeier,
} from '@/lib/api';
import { useAppStore } from '@/lib/store';
import Card from '@/components/ui/Card';
import Badge from '@/components/ui/Badge';

/** 指标含义解释（点击 ? 图标时展开） */
const METRIC_EXPLANATIONS: Record<string, { title: string; desc: string; formula?: string }> = {
  ORR: {
    title: '客观缓解率 (ORR = Objective Response Rate)',
    desc: '肿瘤显著缩小或完全消失的患者比例。是衡量治疗"是否有效"的核心指标。',
    formula: 'ORR = (CR + PR) / 总患者数 × 100%',
  },
  DCR: {
    title: '疾病控制率 (DCR = Disease Control Rate)',
    desc: '肿瘤未进展（包括缩小、稳定）的患者比例。衡量治疗"是否控制住病情"。',
    formula: 'DCR = (CR + PR + SD) / 总患者数 × 100%',
  },
  PFS: {
    title: '无进展生存期 (PFS = Progression-Free Survival)',
    desc: '从治疗开始到肿瘤进展或死亡的时间。中位 PFS 越长越好。',
    formula: '中位数：50% 患者未进展时的天数',
  },
  OS: {
    title: '总生存期 (OS = Overall Survival)',
    desc: '从治疗开始到任何原因死亡的时间。中位 OS 越长越好。',
    formula: '中位数：50% 患者存活时的天数',
  },
  RECIST: {
    title: 'RECIST 1.1 标准',
    desc: '实体瘤疗效评价标准 1.1 版本，用肿瘤直径变化判断疗效：',
    formula:
      'CR (完全缓解): 靶病灶全部消失\nPR (部分缓解): 直径总和缩小 ≥30%\nSD (稳定): 缩小 <30% 或增大 <20%\nPD (进展): 直径总和增大 ≥20% 或出现新病灶',
  },
  CTCAE: {
    title: 'CTCAE v5.0 不良事件',
    desc: '美国 NCI 发布的常用不良事件评价标准（5.0 版本），按严重程度分 1-5 级：',
    formula:
      '1 级：轻度（无症状）\n2 级：中度（影响功能）\n3 级：重度（需要治疗干预）\n4 级：危及生命\n5 级：死亡',
  },
};

const RECIST_VARIANT: Record<string, 'green' | 'blue' | 'gray' | 'red'> = {
  CR: 'green',
  PR: 'blue',
  SD: 'gray',
  PD: 'red',
};

const RECIST_TEXT: Record<string, string> = {
  CR: '完全缓解',
  PR: '部分缓解',
  SD: '稳定',
  PD: '进展',
};

const CTCAE_LEVEL = [
  { grade: 1, label: '1 级·轻度', color: 'bg-green-400' },
  { grade: 2, label: '2 级·中度', color: 'bg-yellow-400' },
  { grade: 3, label: '3 级·重度', color: 'bg-orange-500' },
  { grade: 4, label: '4 级·危及生命', color: 'bg-red-500' },
  { grade: 5, label: '5 级·死亡', color: 'bg-gray-800' },
];

type ModalKind = 'outcome' | 'adverse' | 'recist' | 'km' | null;

export default function EfficacyPage() {
  const { currentProject } = useAppStore();
  const queryClient = useQueryClient();
  const [modal, setModal] = useState<ModalKind>(null);

  const {
    data: summary,
    isLoading: summaryLoading,
    isError: summaryError,
    refetch: refetchSummary,
  } = useQuery({
    queryKey: ['efficacy-summary', currentProject?.id],
    queryFn: () => getEfficacySummary(currentProject?.id),
    enabled: !!currentProject,
  });

  const summaryData: any = summary || {};
  const records: any[] = summaryData.records || [];

  // 录入疗效结局
  const outcomeMutation = useMutation({
    mutationFn: recordOutcome,
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['efficacy-summary'] });
      setModal(null);
    },
  });

  // 录入不良事件
  const adverseMutation = useMutation({
    mutationFn: recordAdverseEvent,
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['efficacy-summary'] });
      setModal(null);
    },
  });

  const statCards = [
    {
      key: 'ORR',
      label: '客观缓解率 (ORR)',
      value: summaryData.overall_orr != null ? `${(summaryData.overall_orr * 100).toFixed(1)}%` : '-',
      sub: '肿瘤缩小或消失的患者比例',
      icon: TrendingUp,
      color: 'text-green-500',
      bg: 'from-green-50 to-emerald-50',
      border: 'border-green-100',
      progress: summaryData.overall_orr != null ? summaryData.overall_orr * 100 : null,
      benchmark: '通常 >30% 视为有效',
    },
    {
      key: 'DCR',
      label: '疾病控制率 (DCR)',
      value: summaryData.overall_dcr != null ? `${(summaryData.overall_dcr * 100).toFixed(1)}%` : '-',
      sub: '肿瘤未进展的患者比例',
      icon: Activity,
      color: 'text-blue-500',
      bg: 'from-blue-50 to-cyan-50',
      border: 'border-blue-100',
      progress: summaryData.overall_dcr != null ? summaryData.overall_dcr * 100 : null,
      benchmark: '通常 >60% 视为可控',
    },
    {
      key: 'PFS',
      label: '中位 PFS (天)',
      value: summaryData.median_pfs_days != null ? summaryData.median_pfs_days : '-',
      sub: '无进展生存期中位数',
      icon: TrendingDown,
      color: 'text-purple-500',
      bg: 'from-purple-50 to-pink-50',
      border: 'border-purple-100',
      progress: summaryData.median_pfs_days != null
        ? Math.min(100, (summaryData.median_pfs_days / 365) * 100)
        : null,
      benchmark: '越长越好',
    },
    {
      key: 'OS',
      label: '中位 OS (天)',
      value: summaryData.median_os_days != null ? summaryData.median_os_days : '-',
      sub: '总生存期中位数',
      icon: TrendingUp,
      color: 'text-orange-500',
      bg: 'from-orange-50 to-amber-50',
      border: 'border-orange-100',
      progress: summaryData.median_os_days != null
        ? Math.min(100, (summaryData.median_os_days / 730) * 100)
        : null,
      benchmark: '越长越好',
    },
  ];

  // 整体治疗健康度
  const healthScore = (() => {
    const orr = summaryData.overall_orr || 0;
    const dcr = summaryData.overall_dcr || 0;
    return Math.round((orr * 0.6 + dcr * 0.4) * 100);
  })();
  const healthLevel =
    healthScore >= 60
      ? { text: '良好', color: 'text-green-700', bg: 'bg-green-50', border: 'border-green-200', icon: CheckCircle2 }
      : healthScore >= 30
      ? { text: '一般', color: 'text-yellow-700', bg: 'bg-yellow-50', border: 'border-yellow-200', icon: Clock }
      : { text: '需关注', color: 'text-red-700', bg: 'bg-red-50', border: 'border-red-200', icon: AlertCircle };

  // RECIST 分布
  const recistDistribution: Record<string, number> = {};
  for (const r of records) {
    if (r.recist_response) {
      recistDistribution[r.recist_response] = (recistDistribution[r.recist_response] || 0) + 1;
    }
  }
  const totalRecist = Object.values(recistDistribution).reduce((a, b) => a + b, 0);

  // AE 分布
  const aeDistribution: Record<string, number> = summaryData.ae_distribution || {};
  const totalAE = Object.values(aeDistribution).reduce((a, b) => a + b, 0);

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-2xl font-bold flex items-center gap-2">
          <Activity className="w-6 h-6" />
          疗效监测
        </h1>
        <p className="text-sm text-gray-500 mt-1">
          RECIST 1.1 标准化疗效评估 + ORR/DCR/Kaplan-Meier 生存分析 + CTCAE v5.0 不良事件
        </p>
        <div className="mt-2 bg-blue-50 border border-blue-200 rounded p-3 text-xs text-blue-800 flex items-start gap-2">
          <Info className="w-4 h-4 mt-0.5 shrink-0" />
          <div>
            <strong>这是什么？</strong>本页面汇总所有患者的疗效数据，按国际标准 RECIST 1.1 评估肿瘤治疗反应，
            并用 ORR/DCR/PFS/OS 等指标衡量治疗效果。点击右上角的工具按钮可手动录入数据或运行分析。
          </div>
        </div>
      </div>

      {/* 操作工具栏 */}
      <div className="flex items-center gap-2 flex-wrap">
        <button
          onClick={() => setModal('outcome')}
          className="flex items-center gap-1.5 px-3 py-1.5 bg-primary-600 text-white rounded text-sm hover:bg-primary-700"
        >
          <Plus className="w-3.5 h-3.5" />
          录入疗效结局
        </button>
        <button
          onClick={() => setModal('adverse')}
          className="flex items-center gap-1.5 px-3 py-1.5 bg-amber-600 text-white rounded text-sm hover:bg-amber-700"
        >
          <AlertCircle className="w-3.5 h-3.5" />
          录入不良事件
        </button>
        <button
          onClick={() => setModal('recist')}
          className="flex items-center gap-1.5 px-3 py-1.5 bg-blue-600 text-white rounded text-sm hover:bg-blue-700"
        >
          <Calculator className="w-3.5 h-3.5" />
          RECIST 分类器
        </button>
        <button
          onClick={() => setModal('km')}
          className="flex items-center gap-1.5 px-3 py-1.5 bg-purple-600 text-white rounded text-sm hover:bg-purple-700"
        >
          <LineChart className="w-3.5 h-3.5" />
          Kaplan-Meier 分析
        </button>
      </div>

      {!currentProject ? (
        <Card className="p-8 text-center text-gray-500">
          <AlertCircle className="w-12 h-12 mx-auto mb-4 text-gray-300" />
          <p>请先选择项目</p>
        </Card>
      ) : summaryError ? (
        <Card className="p-8 text-center">
          <p className="text-sm text-red-600 mb-3">汇总数据加载失败</p>
          <button onClick={() => refetchSummary()} className="text-xs text-primary-600 underline">重试</button>
        </Card>
      ) : summaryLoading ? (
        <Card className="p-8 text-center text-gray-500">
          <Loader2 className="w-6 h-6 animate-spin mx-auto mb-2 text-primary-500" />
          加载汇总数据...
        </Card>
      ) : (
        <>
          {/* 整体治疗健康度 */}
          <Card className={`p-5 border ${healthLevel.border} ${healthLevel.bg}`}>
            <div className="flex items-center gap-4">
              {(() => {
                const Icon = healthLevel.icon;
                return (
                  <div className={`w-12 h-12 rounded-full bg-white flex items-center justify-center ${healthLevel.color}`}>
                    <Icon className="w-6 h-6" />
                  </div>
                );
              })()}
              <div className="flex-1">
                <div className="flex items-center gap-2">
                  <h3 className="text-lg font-semibold">整体治疗健康度</h3>
                  <span className={`text-2xl font-bold ${healthLevel.color}`}>
                    {healthScore}/100 · {healthLevel.text}
                  </span>
                </div>
                <p className="text-xs text-gray-600 mt-1">
                  综合评估：基于 ORR（60% 权重）和 DCR（40% 权重）的加权得分。
                  {healthScore >= 60
                    ? '当前治疗反应良好，建议继续推进。'
                    : healthScore >= 30
                    ? '当前治疗有一定效果但需优化方案。'
                    : '当前治疗效果不佳，建议调整治疗策略或更换靶点/分子。'}
                </p>
                <div className="text-xs text-gray-500 mt-1">
                  共 {summaryData.total_treatments || 0} 个治疗方案 · {summaryData.total_outcomes || 0} 条结局记录
                </div>
              </div>
            </div>
          </Card>

          {/* 4 个核心指标卡片 */}
          <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-4">
            {statCards.map((stat) => {
              const Icon = stat.icon;
              const exp = METRIC_EXPLANATIONS[stat.key];
              return (
                <Card key={stat.label} className={`p-5 bg-gradient-to-br ${stat.bg} border ${stat.border}`}>
                  <div className="flex items-center justify-between mb-2">
                    <div className="flex items-center gap-2">
                      <Icon className={`w-5 h-5 ${stat.color}`} />
                      <span className="text-sm font-medium text-gray-700">{stat.label}</span>
                    </div>
                    <MetricInfoButton title={exp.title} desc={exp.desc} formula={exp.formula} />
                  </div>
                  <p className="text-2xl font-bold text-gray-900">{stat.value}</p>
                  <p className="text-xs text-gray-500 mt-1">{stat.sub}</p>
                  {stat.progress != null && (
                    <div className="mt-2 h-1.5 bg-white/60 rounded-full overflow-hidden">
                      <div
                        className="h-full bg-primary-500 rounded-full"
                        style={{ width: `${Math.min(100, stat.progress)}%` }}
                      />
                    </div>
                  )}
                  <p className="text-[10px] text-gray-500 mt-1">基准：{stat.benchmark}</p>
                </Card>
              );
            })}
          </div>

          {/* 双列布局：RECIST 分布 + CTCAE 不良事件分布 */}
          <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
            {/* RECIST 分布 */}
            <Card className="p-5">
              <div className="flex items-center justify-between mb-3">
                <h3 className="font-semibold flex items-center gap-2">
                  <Activity className="w-4 h-4" />
                  RECIST 响应分布
                  <MetricInfoButton
                    title={METRIC_EXPLANATIONS.RECIST.title}
                    desc={METRIC_EXPLANATIONS.RECIST.desc}
                    formula={METRIC_EXPLANATIONS.RECIST.formula}
                  />
                </h3>
                <span className="text-xs text-gray-500">共 {totalRecist} 条</span>
              </div>
              {totalRecist === 0 ? (
                <div className="text-center py-6 text-xs text-gray-400">
                  暂无 RECIST 评估记录，点击上方"录入疗效结局"开始
                </div>
              ) : (
                <div className="space-y-2">
                  {(['CR', 'PR', 'SD', 'PD'] as const).map((key) => {
                    const count = recistDistribution[key] || 0;
                    const pct = totalRecist > 0 ? (count / totalRecist) * 100 : 0;
                    const colors = { CR: 'bg-green-500', PR: 'bg-blue-500', SD: 'bg-gray-400', PD: 'bg-red-500' };
                    return (
                      <div key={key} className="flex items-center gap-3">
                        <div className="w-20 flex items-center gap-1">
                          <Badge variant={RECIST_VARIANT[key]}>{key}</Badge>
                          <span className="text-xs text-gray-600">{RECIST_TEXT[key]}</span>
                        </div>
                        <div className="flex-1 h-6 bg-gray-100 rounded overflow-hidden relative">
                          <div className={`h-full ${colors[key]} transition-all`} style={{ width: `${pct}%` }} />
                          <span className="absolute inset-0 flex items-center px-2 text-xs font-medium text-gray-700">
                            {count} 例 · {pct.toFixed(1)}%
                          </span>
                        </div>
                      </div>
                    );
                  })}
                </div>
              )}
            </Card>

            {/* CTCAE 不良事件分布 */}
            <Card className="p-5">
              <div className="flex items-center justify-between mb-3">
                <h3 className="font-semibold flex items-center gap-2">
                  <AlertCircle className="w-4 h-4 text-amber-500" />
                  CTCAE v5.0 不良事件分布
                  <MetricInfoButton
                    title={METRIC_EXPLANATIONS.CTCAE.title}
                    desc={METRIC_EXPLANATIONS.CTCAE.desc}
                    formula={METRIC_EXPLANATIONS.CTCAE.formula}
                  />
                </h3>
                <span className="text-xs text-gray-500">共 {totalAE} 项</span>
              </div>
              {totalAE === 0 ? (
                <div className="text-center py-6 text-xs text-gray-400">
                  暂无不良事件记录
                </div>
              ) : (
                <div className="space-y-2">
                  {CTCAE_LEVEL.map((lv) => {
                    const count = aeDistribution[String(lv.grade)] || 0;
                    const pct = totalAE > 0 ? (count / totalAE) * 100 : 0;
                    return (
                      <div key={lv.grade} className="flex items-center gap-3">
                        <div className="w-28 text-xs text-gray-700">{lv.label}</div>
                        <div className="flex-1 h-6 bg-gray-100 rounded overflow-hidden relative">
                          <div className={`h-full ${lv.color} transition-all`} style={{ width: `${pct}%` }} />
                          <span className="absolute inset-0 flex items-center px-2 text-xs font-medium text-gray-700">
                            {count} 项 · {pct.toFixed(1)}%
                          </span>
                        </div>
                      </div>
                    );
                  })}
                </div>
              )}
            </Card>
          </div>

          {/* 按靶点分组 */}
          {summaryData.by_target && Object.keys(summaryData.by_target).length > 0 && (
            <Card className="p-5">
              <h3 className="font-semibold mb-3">按靶点分组疗效</h3>
              <div className="overflow-x-auto">
                <table className="w-full text-sm">
                  <thead>
                    <tr className="border-b text-left text-gray-500">
                      <th className="pb-2">靶点</th>
                      <th className="pb-2">样本数</th>
                      <th className="pb-2">ORR</th>
                      <th className="pb-2">DCR</th>
                      <th className="pb-2">不良事件</th>
                      <th className="pb-2">评估</th>
                    </tr>
                  </thead>
                  <tbody>
                    {Object.entries(summaryData.by_target).map(([target, stats]: [string, any]) => {
                      const orr = stats.orr || 0;
                      const dcr = stats.dcr || 0;
                      const assessment =
                        orr >= 0.4
                          ? { text: '优秀', color: 'text-green-700' }
                          : orr >= 0.2
                          ? { text: '中等', color: 'text-yellow-700' }
                          : { text: '较弱', color: 'text-red-700' };
                      return (
                        <tr key={target} className="border-b">
                          <td className="py-2 font-medium">{target}</td>
                          <td className="py-2">{stats.count}</td>
                          <td className="py-2">
                            <span className={orr >= 0.3 ? 'text-green-700 font-medium' : 'text-gray-700'}>
                              {(orr * 100).toFixed(1)}%
                            </span>
                          </td>
                          <td className="py-2">
                            <span className={dcr >= 0.6 ? 'text-green-700 font-medium' : 'text-gray-700'}>
                              {(dcr * 100).toFixed(1)}%
                            </span>
                          </td>
                          <td className="py-2">
                            {stats.ae_count > 0 ? (
                              <span className={stats.ae_count >= 3 ? 'text-red-700' : 'text-amber-700'}>
                                {stats.ae_count} 项
                              </span>
                            ) : (
                              <span className="text-green-600">无</span>
                            )}
                          </td>
                          <td className={`py-2 font-medium ${assessment.color}`}>{assessment.text}</td>
                        </tr>
                      );
                    })}
                  </tbody>
                </table>
              </div>
            </Card>
          )}

          {/* 疗效记录列表 */}
          <Card className="p-5">
            <div className="flex items-center justify-between mb-3">
              <h3 className="font-semibold flex items-center gap-2">
                <Heart className="w-4 h-4 text-pink-500" />
                疗效记录明细
              </h3>
              <span className="text-xs text-gray-500">{records.length} 条记录</span>
            </div>
            {records.length === 0 ? (
              <div className="text-center py-8 text-gray-400">
                <Activity className="w-12 h-12 mx-auto mb-2 opacity-50" />
                暂无疗效记录
                <p className="text-xs mt-1">
                  点击上方"录入疗效结局"按钮开始记录；疗效数据也可通过实验结果自动同步
                </p>
              </div>
            ) : (
              <div className="overflow-x-auto">
                <table className="w-full text-sm">
                  <thead>
                    <tr className="border-b text-left text-gray-500">
                      <th className="pb-2">记录 ID</th>
                      <th className="pb-2">靶点</th>
                      <th className="pb-2">RECIST 响应</th>
                      <th className="pb-2">随访天数</th>
                      <th className="pb-2">不良事件</th>
                      <th className="pb-2">评估说明</th>
                      <th className="pb-2">创建时间</th>
                    </tr>
                  </thead>
                  <tbody>
                    {records.map((rec: any) => {
                      const recist = rec.recist_response;
                      const interpretation =
                        recist === 'CR'
                          ? '肿瘤完全消失，疗效最佳'
                          : recist === 'PR'
                          ? '肿瘤显著缩小，治疗有效'
                          : recist === 'SD'
                          ? '肿瘤稳定，病情可控'
                          : recist === 'PD'
                          ? '肿瘤进展，需调整方案'
                          : '尚未评估';
                      return (
                        <tr key={rec.id} className="border-b">
                          <td className="py-2 font-mono text-xs">{rec.id?.slice(0, 8)}</td>
                          <td className="py-2 text-xs">{rec.target_name || '-'}</td>
                          <td className="py-2">
                            {recist ? (
                              <div className="flex items-center gap-1">
                                <Badge variant={RECIST_VARIANT[recist] || 'gray'}>{recist}</Badge>
                                <span className="text-xs text-gray-500">{RECIST_TEXT[recist]}</span>
                              </div>
                            ) : (
                              <span className="text-gray-400">-</span>
                            )}
                          </td>
                          <td className="py-2">{rec.follow_up_days != null ? `${rec.follow_up_days} 天` : '-'}</td>
                          <td className="py-2">
                            {rec.adverse_events?.length > 0 ? (
                              <div className="flex items-center gap-1">
                                <Badge variant="red">{rec.adverse_events.length} 项</Badge>
                                <span className="text-xs text-gray-500">
                                  ({rec.adverse_events.map((ae: any) => ae.grade || ae.severity || '?').join(',')})
                                </span>
                              </div>
                            ) : (
                              <span className="text-green-600 text-xs">无</span>
                            )}
                          </td>
                          <td className="py-2 text-xs text-gray-600">{interpretation}</td>
                          <td className="py-2 text-xs">
                            {rec.created_at ? new Date(rec.created_at).toLocaleString() : '-'}
                          </td>
                        </tr>
                      );
                    })}
                  </tbody>
                </table>
              </div>
            )}
          </Card>

          {/* 指标解释总览 */}
          <Card className="p-5 bg-gray-50">
            <h3 className="font-semibold mb-3 flex items-center gap-2">
              <Info className="w-4 h-4" /> 指标含义速查
            </h3>
            <div className="grid grid-cols-1 md:grid-cols-2 gap-3 text-xs">
              {Object.entries(METRIC_EXPLANATIONS).map(([k, v]) => (
                <div key={k} className="bg-white p-3 rounded border border-gray-200">
                  <div className="font-semibold text-gray-900 mb-1">{v.title}</div>
                  <div className="text-gray-600">{v.desc}</div>
                  {v.formula && (
                    <div className="mt-2 font-mono text-[10px] bg-gray-50 p-2 rounded text-gray-700 whitespace-pre-wrap">
                      {v.formula}
                    </div>
                  )}
                </div>
              ))}
            </div>
          </Card>
        </>
      )}

      {/* ========== 模态框：录入疗效结局 ========== */}
      {modal === 'outcome' && (
        <RecordOutcomeModal
          onClose={() => setModal(null)}
          onSubmit={(payload) => outcomeMutation.mutate(payload)}
          loading={outcomeMutation.isPending}
          error={outcomeMutation.error ? '录入失败，请检查治疗 ID 是否存在' : null}
        />
      )}

      {/* ========== 模态框：录入不良事件 ========== */}
      {modal === 'adverse' && (
        <RecordAdverseEventModal
          onClose={() => setModal(null)}
          onSubmit={(payload) => adverseMutation.mutate(payload)}
          loading={adverseMutation.isPending}
          error={adverseMutation.error ? '录入失败，请检查治疗 ID 是否存在' : null}
        />
      )}

      {/* ========== 模态框：RECIST 分类器 ========== */}
      {modal === 'recist' && (
        <RecistClassifyModal onClose={() => setModal(null)} />
      )}

      {/* ========== 模态框：Kaplan-Meier 分析 ========== */}
      {modal === 'km' && <KaplanMeierModal onClose={() => setModal(null)} />}
    </div>
  );
}

/** 指标解释按钮（点击展开详情） */
function MetricInfoButton({
  title,
  desc,
  formula,
}: {
  title: string;
  desc: string;
  formula?: string;
}) {
  return (
    <button
      type="button"
      onClick={(e) => {
        e.stopPropagation();
        alert(`${title}\n\n${desc}${formula ? `\n\n计算方法：\n${formula}` : ''}`);
      }}
      className="p-1 rounded-full hover:bg-gray-200 text-gray-400 hover:text-gray-600"
      title="点击查看指标解释"
    >
      <Info className="w-3.5 h-3.5" />
    </button>
  );
}

// ========== 模态框组件 ==========

function ModalShell({
  title,
  icon: Icon,
  iconColor,
  onClose,
  children,
}: {
  title: string;
  icon: any;
  iconColor: string;
  onClose: () => void;
  children: React.ReactNode;
}) {
  return (
    <div className="fixed inset-0 bg-black/50 flex items-center justify-center z-50 p-4">
      <div className="bg-white rounded-lg max-w-2xl w-full max-h-[88vh] overflow-y-auto">
        <div className="flex items-center justify-between px-5 py-3 border-b sticky top-0 bg-white z-10">
          <h3 className="font-semibold flex items-center gap-2">
            <Icon className={`w-4 h-4 ${iconColor}`} />
            {title}
          </h3>
          <button onClick={onClose} className="text-gray-400 hover:text-gray-600">
            <X className="w-5 h-5" />
          </button>
        </div>
        <div className="p-5">{children}</div>
      </div>
    </div>
  );
}

function RecordOutcomeModal({
  onClose,
  onSubmit,
  loading,
  error,
}: {
  onClose: () => void;
  onSubmit: (payload: any) => void;
  loading: boolean;
  error: string | null;
}) {
  const [treatmentId, setTreatmentId] = useState('');
  const [response, setResponse] = useState('');
  const [baseline, setBaseline] = useState('');
  const [current, setCurrent] = useState('');
  const [followUpDays, setFollowUpDays] = useState('');
  const [event, setEvent] = useState<'1' | '0'>('1');

  const handleSubmit = () => {
    if (!treatmentId.trim()) return;
    const lesions =
      baseline && current
        ? [{ baseline_mm: parseFloat(baseline), current_mm: parseFloat(current) }]
        : undefined;
    onSubmit({
      treatment_id: treatmentId.trim(),
      outcome: {
        response: response || undefined,
        lesions,
        time: followUpDays ? parseFloat(followUpDays) : undefined,
        event: parseInt(event, 10),
      },
    });
  };

  return (
    <ModalShell title="录入疗效结局" icon={Plus} iconColor="text-primary-600" onClose={onClose}>
      <div className="space-y-3">
        <div className="bg-blue-50 border border-blue-200 rounded p-3 text-xs text-blue-800">
          未填 RECIST 响应时，系统将根据病灶测量值自动按 RECIST 1.1 分类。
        </div>
        <div>
          <label className="text-sm font-medium">治疗方案 ID *</label>
          <input
            value={treatmentId}
            onChange={(e) => setTreatmentId(e.target.value)}
            placeholder="UUID（来自治疗方案模块）"
            className="w-full mt-1 px-3 py-2 border rounded font-mono text-sm"
          />
        </div>
        <div>
          <label className="text-sm font-medium">RECIST 响应（可选）</label>
          <div className="grid grid-cols-4 gap-2 mt-1">
            {(['CR', 'PR', 'SD', 'PD'] as const).map((r) => (
              <button
                key={r}
                onClick={() => setResponse(response === r ? '' : r)}
                className={`px-2 py-1.5 text-xs rounded border ${
                  response === r
                    ? 'bg-primary-600 text-white border-primary-600'
                    : 'bg-white text-gray-700 border-gray-300'
                }`}
              >
                {r} · {RECIST_TEXT[r]}
              </button>
            ))}
          </div>
        </div>
        <div className="grid grid-cols-2 gap-3">
          <div>
            <label className="text-sm font-medium">基线病灶直径（mm）</label>
            <input
              type="number"
              value={baseline}
              onChange={(e) => setBaseline(e.target.value)}
              placeholder="如 45.0"
              className="w-full mt-1 px-3 py-2 border rounded text-sm"
            />
          </div>
          <div>
            <label className="text-sm font-medium">当前病灶直径（mm）</label>
            <input
              type="number"
              value={current}
              onChange={(e) => setCurrent(e.target.value)}
              placeholder="如 30.0"
              className="w-full mt-1 px-3 py-2 border rounded text-sm"
            />
          </div>
        </div>
        <div className="grid grid-cols-2 gap-3">
          <div>
            <label className="text-sm font-medium">随访天数</label>
            <input
              type="number"
              value={followUpDays}
              onChange={(e) => setFollowUpDays(e.target.value)}
              placeholder="如 180"
              className="w-full mt-1 px-3 py-2 border rounded text-sm"
            />
          </div>
          <div>
            <label className="text-sm font-medium">事件类型</label>
            <select
              value={event}
              onChange={(e) => setEvent(e.target.value as '1' | '0')}
              className="w-full mt-1 px-3 py-2 border rounded text-sm"
            >
              <option value="1">1 = 死亡/进展</option>
              <option value="0">0 = 删失（censored）</option>
            </select>
          </div>
        </div>
        {error && <div className="text-red-600 text-sm">{error}</div>}
        <button
          onClick={handleSubmit}
          disabled={!treatmentId.trim() || loading}
          className="flex items-center gap-2 px-4 py-2 bg-primary-600 text-white rounded hover:bg-primary-700 disabled:opacity-50"
        >
          {loading && <Loader2 className="w-4 h-4 animate-spin" />}
          {loading ? '提交中...' : '提交'}
        </button>
      </div>
    </ModalShell>
  );
}

function RecordAdverseEventModal({
  onClose,
  onSubmit,
  loading,
  error,
}: {
  onClose: () => void;
  onSubmit: (payload: any) => void;
  loading: boolean;
  error: string | null;
}) {
  const [treatmentId, setTreatmentId] = useState('');
  const [symptom, setSymptom] = useState('');
  const [severity, setSeverity] = useState('1');
  const [description, setDescription] = useState('');

  const handleSubmit = () => {
    if (!treatmentId.trim() || !symptom.trim()) return;
    onSubmit({
      treatment_id: treatmentId.trim(),
      event: {
        symptom: symptom.trim(),
        severity,
        description: description.trim() || undefined,
      },
    });
  };

  return (
    <ModalShell title="录入不良事件" icon={AlertCircle} iconColor="text-amber-600" onClose={onClose}>
      <div className="space-y-3">
        <div className="bg-amber-50 border border-amber-200 rounded p-3 text-xs text-amber-800">
          系统将根据症状描述和严重度自动按 CTCAE v5.0 分级（1-5 级）。
        </div>
        <div>
          <label className="text-sm font-medium">治疗方案 ID *</label>
          <input
            value={treatmentId}
            onChange={(e) => setTreatmentId(e.target.value)}
            placeholder="UUID"
            className="w-full mt-1 px-3 py-2 border rounded font-mono text-sm"
          />
        </div>
        <div>
          <label className="text-sm font-medium">症状 *</label>
          <input
            value={symptom}
            onChange={(e) => setSymptom(e.target.value)}
            placeholder="如 恶心、脱发、白细胞减少"
            className="w-full mt-1 px-3 py-2 border rounded text-sm"
          />
        </div>
        <div>
          <label className="text-sm font-medium">严重度</label>
          <select
            value={severity}
            onChange={(e) => setSeverity(e.target.value)}
            className="w-full mt-1 px-3 py-2 border rounded text-sm"
          >
            <option value="1">1 级 · 轻度</option>
            <option value="2">2 级 · 中度</option>
            <option value="3">3 级 · 重度</option>
            <option value="4">4 级 · 危及生命</option>
            <option value="5">5 级 · 死亡</option>
          </select>
        </div>
        <div>
          <label className="text-sm font-medium">详细描述</label>
          <textarea
            value={description}
            onChange={(e) => setDescription(e.target.value)}
            placeholder="可填：住院、危及生命 等关键词辅助 CTCAE 分级"
            rows={3}
            className="w-full mt-1 px-3 py-2 border rounded text-sm"
          />
        </div>
        {error && <div className="text-red-600 text-sm">{error}</div>}
        <button
          onClick={handleSubmit}
          disabled={!treatmentId.trim() || !symptom.trim() || loading}
          className="flex items-center gap-2 px-4 py-2 bg-amber-600 text-white rounded hover:bg-amber-700 disabled:opacity-50"
        >
          {loading && <Loader2 className="w-4 h-4 animate-spin" />}
          {loading ? '提交中...' : '提交'}
        </button>
      </div>
    </ModalShell>
  );
}

function RecistClassifyModal({ onClose }: { onClose: () => void }) {
  const [lesions, setLesions] = useState<{ baseline_mm: string; current_mm: string }[]>([
    { baseline_mm: '', current_mm: '' },
  ]);
  const [result, setResult] = useState<any>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const handleAdd = () => setLesions([...lesions, { baseline_mm: '', current_mm: '' }]);
  const handleRemove = (i: number) => setLesions(lesions.filter((_, idx) => idx !== i));
  const handleChange = (i: number, key: 'baseline_mm' | 'current_mm', val: string) => {
    setLesions(lesions.map((l, idx) => (idx === i ? { ...l, [key]: val } : l)));
  };

  const handleClassify = async () => {
    const parsed = lesions
      .filter((l) => l.baseline_mm && l.current_mm)
      .map((l) => ({ baseline_mm: parseFloat(l.baseline_mm), current_mm: parseFloat(l.current_mm) }));
    if (parsed.length === 0) {
      setError('请至少填写一组病灶测量值');
      return;
    }
    setLoading(true);
    setError(null);
    try {
      const r = await recistClassify({ lesions: parsed });
      setResult(r);
    } catch (e: any) {
      setError(e.response?.data?.detail || e.message || '分类失败');
    } finally {
      setLoading(false);
    }
  };

  return (
    <ModalShell title="RECIST 1.1 分类器" icon={Calculator} iconColor="text-blue-600" onClose={onClose}>
      <div className="space-y-3">
        <div className="bg-blue-50 border border-blue-200 rounded p-3 text-xs text-blue-800 whitespace-pre-wrap">
          {METRIC_EXPLANATIONS.RECIST.formula}
        </div>
        {lesions.map((l, i) => (
          <div key={i} className="flex items-center gap-2">
            <span className="text-xs text-gray-500 w-12">病灶 {i + 1}</span>
            <input
              type="number"
              value={l.baseline_mm}
              onChange={(e) => handleChange(i, 'baseline_mm', e.target.value)}
              placeholder="基线（mm）"
              className="flex-1 px-2 py-1.5 border rounded text-sm"
            />
            <input
              type="number"
              value={l.current_mm}
              onChange={(e) => handleChange(i, 'current_mm', e.target.value)}
              placeholder="当前（mm）"
              className="flex-1 px-2 py-1.5 border rounded text-sm"
            />
            {lesions.length > 1 && (
              <button onClick={() => handleRemove(i)} className="text-gray-400 hover:text-red-500">
                <X className="w-4 h-4" />
              </button>
            )}
          </div>
        ))}
        <button
          onClick={handleAdd}
          className="flex items-center gap-1 text-xs text-blue-600 hover:text-blue-700"
        >
          <Plus className="w-3.5 h-3.5" /> 添加病灶
        </button>

        <button
          onClick={handleClassify}
          disabled={loading}
          className="flex items-center gap-2 px-4 py-2 bg-blue-600 text-white rounded hover:bg-blue-700 disabled:opacity-50"
        >
          {loading && <Loader2 className="w-4 h-4 animate-spin" />}
          {loading ? '计算中...' : '运行分类'}
        </button>

        {error && <div className="text-red-600 text-sm">{error}</div>}

        {result && (
          <div className="bg-gradient-to-br from-blue-50 to-cyan-50 border border-blue-200 rounded-lg p-4 space-y-2">
            <div className="text-xs text-gray-500">RECIST 1.1 分类结果</div>
            <div className="flex items-center gap-3">
              <Badge variant={RECIST_VARIANT[result.classification] || 'gray'}>
                {result.classification}
              </Badge>
              <span className="text-lg font-bold text-gray-900">
                {RECIST_TEXT[result.classification]}
              </span>
            </div>
            <div className="text-xs text-gray-600">
              共 {result.lesions_count} 个病灶 ·
              直径总和变化：
              {(() => {
                const baseline = result.lesions.reduce((a: number, l: any) => a + (l.baseline_mm || 0), 0);
                const current = result.lesions.reduce((a: number, l: any) => a + (l.current_mm || 0), 0);
                const pct = baseline > 0 ? ((current - baseline) / baseline * 100).toFixed(1) : '0';
                return `${baseline.toFixed(1)}mm → ${current.toFixed(1)}mm (${pct}%)`;
              })()}
            </div>
          </div>
        )}
      </div>
    </ModalShell>
  );
}

function KaplanMeierModal({ onClose }: { onClose: () => void }) {
  const [events, setEvents] = useState<{ time: string; event: '1' | '0' }[]>([
    { time: '', event: '1' },
  ]);
  const [result, setResult] = useState<any>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const handleAdd = () => setEvents([...events, { time: '', event: '1' }]);
  const handleRemove = (i: number) => setEvents(events.filter((_, idx) => idx !== i));
  const handleChange = (i: number, key: 'time' | 'event', val: string) => {
    setEvents(events.map((e, idx) => (idx === i ? { ...e, [key]: val } : e)));
  };

  const handleAnalyze = async () => {
    const parsed = events
      .filter((e) => e.time)
      .map((e) => ({ time: parseFloat(e.time), event: parseInt(e.event, 10) }));
    if (parsed.length === 0) {
      setError('请至少填写一个事件');
      return;
    }
    setLoading(true);
    setError(null);
    try {
      const r = await kaplanMeier({ events: parsed });
      setResult(r);
    } catch (e: any) {
      setError(e.response?.data?.detail || e.message || '分析失败');
    } finally {
      setLoading(false);
    }
  };

  return (
    <ModalShell title="Kaplan-Meier 生存分析" icon={LineChart} iconColor="text-purple-600" onClose={onClose}>
      <div className="space-y-3">
        <div className="bg-purple-50 border border-purple-200 rounded p-3 text-xs text-purple-800">
          输入每个患者的事件数据（随访时间 + 是否发生事件）。event=1 表示死亡或进展，event=0 表示删失（censored）。
        </div>
        {events.map((e, i) => (
          <div key={i} className="flex items-center gap-2">
            <span className="text-xs text-gray-500 w-12">患者 {i + 1}</span>
            <input
              type="number"
              value={e.time}
              onChange={(ev) => handleChange(i, 'time', ev.target.value)}
              placeholder="随访天数"
              className="flex-1 px-2 py-1.5 border rounded text-sm"
            />
            <select
              value={e.event}
              onChange={(ev) => handleChange(i, 'event', ev.target.value)}
              className="px-2 py-1.5 border rounded text-sm"
            >
              <option value="1">1 = 事件</option>
              <option value="0">0 = 删失</option>
            </select>
            {events.length > 1 && (
              <button onClick={() => handleRemove(i)} className="text-gray-400 hover:text-red-500">
                <X className="w-4 h-4" />
              </button>
            )}
          </div>
        ))}
        <button
          onClick={handleAdd}
          className="flex items-center gap-1 text-xs text-purple-600 hover:text-purple-700"
        >
          <Plus className="w-3.5 h-3.5" /> 添加患者
        </button>

        <button
          onClick={handleAnalyze}
          disabled={loading}
          className="flex items-center gap-2 px-4 py-2 bg-purple-600 text-white rounded hover:bg-purple-700 disabled:opacity-50"
        >
          {loading && <Loader2 className="w-4 h-4 animate-spin" />}
          {loading ? '分析中...' : '运行 KM 分析'}
        </button>

        {error && <div className="text-red-600 text-sm">{error}</div>}

        {result && (
          <div className="space-y-3">
            <div className="grid grid-cols-3 gap-3">
              <div className="bg-purple-50 p-3 rounded border border-purple-100">
                <div className="text-xs text-gray-500">总样本数</div>
                <div className="text-xl font-bold text-purple-700">{result.n_total}</div>
              </div>
              <div className="bg-purple-50 p-3 rounded border border-purple-100">
                <div className="text-xs text-gray-500">事件数</div>
                <div className="text-xl font-bold text-purple-700">{result.n_events}</div>
              </div>
              <div className="bg-purple-50 p-3 rounded border border-purple-100">
                <div className="text-xs text-gray-500">中位生存期</div>
                <div className="text-xl font-bold text-purple-700">
                  {result.median_survival != null ? `${result.median_survival} 天` : '未达到'}
                </div>
              </div>
            </div>
            {/* 生存曲线（SVG 简易绘制） */}
            {result.survival_curve && result.survival_curve.length > 1 && (
              <SurvivalCurvePlot curve={result.survival_curve} />
            )}
          </div>
        )}
      </div>
    </ModalShell>
  );
}

/** 简易 SVG 生存曲线绘制 */
function SurvivalCurvePlot({ curve }: { curve: { time: number; survival: number; n_at_risk: number }[] }) {
  const W = 500;
  const H = 280;
  const PADDING = 40;
  const plotW = W - PADDING * 2;
  const plotH = H - PADDING * 2;

  const maxTime = Math.max(...curve.map((p) => p.time), 1);
  const points = curve.map((p) => ({
    x: PADDING + (p.time / maxTime) * plotW,
    y: PADDING + (1 - p.survival) * plotH,
  }));
  const pathD = points
    .map((p, i) => `${i === 0 ? 'M' : 'L'} ${p.x.toFixed(1)} ${p.y.toFixed(1)}`)
    .join(' ');

  return (
    <div className="bg-white border rounded p-3">
      <div className="text-xs text-gray-500 mb-1">Kaplan-Meier 生存曲线</div>
      <svg viewBox={`0 0 ${W} ${H}`} className="w-full">
        {/* 坐标轴 */}
        <line x1={PADDING} y1={PADDING} x2={PADDING} y2={H - PADDING} stroke="#666" />
        <line x1={PADDING} y1={H - PADDING} x2={W - PADDING} y2={H - PADDING} stroke="#666" />
        {/* 50% 参考线 */}
        <line
          x1={PADDING}
          y1={PADDING + plotH / 2}
          x2={W - PADDING}
          y2={PADDING + plotH / 2}
          stroke="#ddd"
          strokeDasharray="4 4"
        />
        <text x={W - PADDING} y={PADDING + plotH / 2 - 4} textAnchor="end" fontSize="10" fill="#999">
          50%
        </text>
        {/* 曲线 */}
        <path d={pathD} stroke="#7c3aed" strokeWidth="2" fill="none" />
        {/* 数据点 */}
        {points.map((p, i) => (
          <circle key={i} cx={p.x} cy={p.y} r="2.5" fill="#7c3aed" />
        ))}
        {/* 坐标轴标签 */}
        <text x={W / 2} y={H - 8} textAnchor="middle" fontSize="11" fill="#666">
          随访时间（天）
        </text>
        <text
          x={12}
          y={H / 2}
          textAnchor="middle"
          fontSize="11"
          fill="#666"
          transform={`rotate(-90 12 ${H / 2})`}
        >
          生存概率
        </text>
      </svg>
    </div>
  );
}
