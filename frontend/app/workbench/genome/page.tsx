'use client';

import { useState, useMemo } from 'react';
import { useRouter } from 'next/navigation';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import {
  Dna,
  Upload,
  ListChecks,
  Sparkles,
  FileText,
  ChevronRight,
  ChevronLeft,
  History,
  Loader2,
  Link2,
  Target as TargetIcon,
  Pill,
  Combine,
  Filter,
  ArrowRight,
} from 'lucide-react';
import { useAppStore } from '@/lib/store';
import {
  matchGenotype,
  scoreRisk,
  interpret,
  generateRecommendations,
  personalizedTreatment,
  listRecommendations,
  listAssessments,
  getTargets,
} from '@/lib/api';
import Button from '@/components/ui/Button';
import Card from '@/components/ui/Card';
import Badge from '@/components/ui/Badge';
import ProgressBar from '@/components/ui/ProgressBar';
import GenomeUploader from '@/components/genome/GenomeUploader';
import GenomeFileList from '@/components/genome/GenomeFileList';
import TraitSelector from '@/components/genome/TraitSelector';
import LociSearchPanel from '@/components/genome/LociSearchPanel';
import RiskScoreChart from '@/components/genome/RiskScoreChart';
import InterpretationReport from '@/components/genome/InterpretationReport';
import RecommendationList from '@/components/genome/RecommendationList';
import PersonalizedTreatmentCard from '@/components/genome/PersonalizedTreatmentCard';
import AssessmentHistory from '@/components/genome/AssessmentHistory';
import AIInsightBanner from '@/components/coscientist/AIInsightBanner';

const STEPS = [
  { id: 1, label: '上传文件', icon: Upload },
  { id: 2, label: '选择性状', icon: ListChecks },
  { id: 3, label: 'AI 分析', icon: Sparkles },
  { id: 4, label: '查看报告', icon: FileText },
];

export default function GenomePage() {
  const { currentProject, setSelectedGenome: setStoreGenomeId } = useAppStore();
  const queryClient = useQueryClient();
  const router = useRouter();

  const [step, setStep] = useState(1);
  const [selectedGenome, setSelectedGenome] = useState<any>(null);
  const [selectedTraitIds, setSelectedTraitIds] = useState<string[]>([]);
  const [activeTraitId, setActiveTraitId] = useState<string | null>(null);
  const [activeTraitName, setActiveTraitName] = useState<string>('');
  const [currentAssessment, setCurrentAssessment] = useState<any>(null);
  const [interpretation, setInterpretation] = useState<any>(null);
  const [recommendations, setRecommendations] = useState<any[]>([]);
  const [treatmentData, setTreatmentData] = useState<any>(null);
  const [currentMatches, setCurrentMatches] = useState<any[]>([]);
  const [historyOpen, setHistoryOpen] = useState(false);

  // 拉取项目内已发现的靶点 — 用于和基因组风险变异联动（仅 Step 4 报告页加载）
  const { data: targetsData } = useQuery({
    queryKey: ['targets-for-genome-linkage', currentProject?.id],
    queryFn: () => getTargets(),
    enabled: !!currentProject && step === 4,
  });
  const projectTargets: any[] = useMemo(
    () => ((targetsData as any)?.data ?? (targetsData as any)?.items) || (Array.isArray(targetsData) ? targetsData : []) || [],
    [targetsData]
  );

  // ===== Mutations =====
  const matchMutation = useMutation({
    mutationFn: ({ genomeId, traitId }: { genomeId: string; traitId: string }) =>
      matchGenotype(genomeId, traitId),
    onSuccess: (res) => {
      const data = res?.data ?? res;
      setCurrentMatches(data?.matches || []);
    },
  });

  const scoreMutation = useMutation({
    mutationFn: ({ genomeId, traitId }: { genomeId: string; traitId: string }) =>
      scoreRisk(genomeId, traitId),
    onSuccess: (res) => {
      const assessment = res?.data ?? res;
      setCurrentAssessment(assessment);
    },
  });

  const interpretMutation = useMutation({
    mutationFn: (assessmentId: string) =>
      interpret(assessmentId, { use_llm: true }),
    onSuccess: (res) => {
      const data = res?.data ?? res;
      setInterpretation(data);
      queryClient.invalidateQueries({ queryKey: ['genome-assessments'] });
    },
  });

  const recMutation = useMutation({
    mutationFn: (assessmentId: string) => generateRecommendations(assessmentId),
    onSuccess: (res) => {
      const data = res?.data ?? res;
      setRecommendations(data?.recommendations || []);
    },
  });

  const treatmentMutation = useMutation({
    mutationFn: (genomeId: string) =>
      personalizedTreatment({
        personal_genome_id: genomeId,
        project_id: currentProject?.id,
      }),
    onSuccess: (res) => {
      const data = res?.data ?? res;
      setTreatmentData(data);
    },
  });

  const runAnalysis = async () => {
    if (!selectedGenome || selectedTraitIds.length === 0) return;
    const traitId = selectedTraitIds[0];
    setActiveTraitId(traitId);
    try {
      // 1. 匹配基因型
      const matchRes: any = await matchMutation.mutateAsync({
        genomeId: selectedGenome.id,
        traitId,
      });
      const matchData = matchRes?.data ?? matchRes;
      setCurrentMatches(matchData?.matches || []);

      // 2. 风险评估
      const scoreRes: any = await scoreMutation.mutateAsync({
        genomeId: selectedGenome.id,
        traitId,
      });
      const assessment = scoreRes?.data ?? scoreRes;
      setCurrentAssessment(assessment);

      // 3. 进入下一步
      setStep(4);
    } catch (e) {
      // 错误已被 mutation onError 处理
    }
  };

  const handleGenerateReport = async () => {
    if (!currentAssessment?.id) return;
    try {
      await Promise.all([
        interpretMutation.mutateAsync(currentAssessment.id),
        recMutation.mutateAsync(currentAssessment.id),
      ]);
    } catch (e) {
      // 错误已被 mutation onError 处理
    }
  };

  const handleGenerateTreatment = async () => {
    if (!selectedGenome?.id) return;
    try {
      await treatmentMutation.mutateAsync(selectedGenome.id);
    } catch (e) {
      // 错误已被 mutation onError 处理
    }
  };

  const handleSelectHistory = (assessment: any) => {
    setCurrentAssessment(assessment);
    setInterpretation(null);
    setRecommendations([]);
    setTreatmentData(null);
    setHistoryOpen(false);
    setStep(4);
  };

  // 计算"基因组风险变异 ↔ 项目已发现靶点"的交叉关联
  // 用户的风险位点 gene_symbol 与项目内已发现的靶点 gene_symbol 匹配
  const linkedTargets = useMemo(() => {
    if (!projectTargets.length || !currentMatches.length) return [];
    const userRiskGenes = new Set(
      currentMatches
        .filter((m) => m.is_risk && m.gene_symbol)
        .map((m) => (m.gene_symbol as string).toUpperCase())
    );
    return projectTargets
      .filter((t) => t.gene_symbol && userRiskGenes.has(String(t.gene_symbol).toUpperCase()))
      .map((t) => {
        const userMatch = currentMatches.find(
          (m) =>
            m.is_risk &&
            m.gene_symbol &&
            String(m.gene_symbol).toUpperCase() === String(t.gene_symbol).toUpperCase()
        );
        return {
          ...t,
          user_risk_genotype: userMatch?.user_genotype,
          user_risk_score: userMatch?.risk_score,
          user_rs_id: userMatch?.rsid,
        };
      });
  }, [projectTargets, currentMatches]);

  // 派生：未被项目覆盖的用户风险基因（提示研究空白）
  const uncoveredRiskGenes = useMemo(() => {
    if (!currentMatches.length) return [];
    const projectGenes = new Set(
      projectTargets
        .filter((t) => t.gene_symbol)
        .map((t) => String(t.gene_symbol).toUpperCase())
    );
    const seen = new Set<string>();
    const result: any[] = [];
    for (const m of currentMatches) {
      if (!m.is_risk || !m.gene_symbol) continue;
      const gene = String(m.gene_symbol).toUpperCase();
      if (projectGenes.has(gene) || seen.has(gene)) continue;
      seen.add(gene);
      result.push({
        gene_symbol: m.gene_symbol,
        rsid: m.rsid,
        user_genotype: m.user_genotype,
        risk_score: m.risk_score,
      });
    }
    return result.slice(0, 10);
  }, [projectTargets, currentMatches]);

  return (
    <div className="space-y-6">
      {/* 标题区 */}
      <div className="flex items-start justify-between flex-wrap gap-3">
        <div>
          <h1 className="text-2xl font-bold flex items-center gap-2">
            <Dna className="w-6 h-6 text-primary-600" />
            个人基因组解读
          </h1>
          <p className="text-sm text-gray-500 mt-1">
            上传 SNP 芯片数据 → 选择性状 → AI 检索位点 → 风险评估 → LLM 解读 → 生活建议
          </p>
        </div>
        <Button
          variant="ghost"
          onClick={() => setHistoryOpen(true)}
          disabled={!selectedGenome?.id}
        >
          <History className="w-4 h-4" />
          历史评估
        </Button>
      </div>

      <AIInsightBanner entityType="assessment" projectId={currentProject?.id} />

      {/* Stepper */}
      <div className="flex items-center justify-between max-w-3xl">
        {STEPS.map((s, idx) => {
          const Icon = s.icon;
          const active = step === s.id;
          const done = step > s.id;
          return (
            <div key={s.id} className="flex items-center flex-1 last:flex-none">
              <div className="flex items-center gap-2">
                <div
                  className={`w-8 h-8 rounded-full flex items-center justify-center text-xs font-bold transition-colors ${
                    active
                      ? 'bg-primary-600 text-white'
                      : done
                        ? 'bg-green-500 text-white'
                        : 'bg-gray-200 text-gray-500'
                  }`}
                >
                  {done ? '✓' : <Icon className="w-4 h-4" />}
                </div>
                <span
                  className={`text-xs font-medium ${
                    active ? 'text-primary-700' : done ? 'text-green-700' : 'text-gray-500'
                  }`}
                >
                  {s.label}
                </span>
              </div>
              {idx < STEPS.length - 1 && (
                <div
                  className={`h-0.5 flex-1 mx-3 ${
                    step > s.id ? 'bg-green-500' : 'bg-gray-200'
                  }`}
                />
              )}
            </div>
          );
        })}
      </div>

      {/* Step 1: 上传 */}
      {step === 1 && (
        <Card title="Step 1 · 上传 SNP 芯片文件">
          <div className="space-y-4">
            <GenomeUploader
              projectId={currentProject?.id}
              onUploaded={(g) => {
                setSelectedGenome(g);
                setStoreGenomeId(g.id);
              }}
            />
            <div>
              <div className="text-xs font-medium text-gray-600 mb-2">
                或选择已上传的文件：
              </div>
              <GenomeFileList
                selectedGenomeId={selectedGenome?.id}
                onSelect={(g) => {
                  setSelectedGenome(g);
                  setStoreGenomeId(g.id);
                }}
              />
            </div>
            <div className="flex justify-end">
              <Button
                disabled={!selectedGenome}
                onClick={() => setStep(2)}
              >
                下一步：选择性状
                <ChevronRight className="w-4 h-4" />
              </Button>
            </div>
          </div>
        </Card>
      )}

      {/* Step 2: 选择性状 */}
      {step === 2 && (
        <Card title="Step 2 · 选择感兴趣的性状">
          <div className="space-y-4">
            {selectedGenome && (
              <div className="rounded-lg bg-blue-50 border border-blue-200 p-3 text-xs text-blue-800">
                已选基因组：<strong>{selectedGenome.file_name}</strong> · 变体数：
                {selectedGenome.total_variants ?? '—'}
              </div>
            )}
            <TraitSelector
              selectedTraitIds={selectedTraitIds}
              onChange={setSelectedTraitIds}
            />
            <div className="flex justify-between">
              <Button variant="ghost" onClick={() => setStep(1)}>
                <ChevronLeft className="w-4 h-4" />
                上一步
              </Button>
              <Button
                disabled={selectedTraitIds.length === 0}
                onClick={() => {
                  setActiveTraitId(selectedTraitIds[0]);
                  setStep(3);
                }}
              >
                下一步：AI 分析
                <ChevronRight className="w-4 h-4" />
              </Button>
            </div>
          </div>
        </Card>
      )}

      {/* Step 3: AI 分析 */}
      {step === 3 && (
        <Card title="Step 3 · AI 检索位点 + 基因型匹配 + 风险评估">
          <div className="space-y-4">
            <LociSearchPanel
              traitId={activeTraitId}
              traitName={activeTraitName}
              onSearched={() => {
                queryClient.invalidateQueries({
                  queryKey: ['genome-trait-loci', activeTraitId],
                });
              }}
            />

            <div className="rounded-lg border border-primary-200 bg-primary-50/40 p-4">
              <div className="text-sm font-semibold text-primary-700 mb-2">
                流程操作
              </div>
              <p className="text-xs text-gray-600 mb-3">
                确认已通过 AI 检索到足够位点后，依次执行基因型匹配与风险评估。
              </p>
              <div className="flex flex-wrap gap-2">
                <Button
                  variant="secondary"
                  loading={matchMutation.isPending}
                  disabled={!selectedGenome || !activeTraitId || matchMutation.isPending}
                  onClick={() =>
                    selectedGenome &&
                    activeTraitId &&
                    matchMutation.mutate({
                      genomeId: selectedGenome.id,
                      traitId: activeTraitId,
                    })
                  }
                >
                  <Dna className="w-4 h-4" />
                  1. 基因型匹配
                </Button>
                <Button
                  variant="secondary"
                  loading={scoreMutation.isPending}
                  disabled={
                    !selectedGenome ||
                    !activeTraitId ||
                    currentMatches.length === 0 ||
                    scoreMutation.isPending
                  }
                  onClick={() =>
                    selectedGenome &&
                    activeTraitId &&
                    scoreMutation.mutate({
                      genomeId: selectedGenome.id,
                      traitId: activeTraitId,
                    })
                  }
                >
                  <Sparkles className="w-4 h-4" />
                  2. 风险评估
                </Button>
                <Button
                  disabled={!currentAssessment}
                  onClick={() => setStep(4)}
                >
                  <ChevronRight className="w-4 h-4" />
                  查看报告
                </Button>
              </div>
            </div>

            {/* 实时进度 */}
            {(matchMutation.isPending || scoreMutation.isPending) && (
              <ProgressBar
                status="running"
                percent={50}
                message={
                  matchMutation.isPending
                    ? '正在比对用户基因型与位点...'
                    : '正在计算多基因风险评分...'
                }
              />
            )}

            {/* 匹配结果摘要 */}
            {currentMatches.length > 0 && (
              <div className="rounded-lg border border-gray-200 bg-white p-3 text-xs">
                <div className="font-medium text-gray-700 mb-2">
                  匹配结果：{currentMatches.length} 个位点 · 风险位点{' '}
                  <span className="text-red-600 font-bold">
                    {currentMatches.filter((m) => m.is_risk).length}
                  </span>{' '}
                  个
                </div>
                <div className="space-y-1 max-h-48 overflow-y-auto">
                  {currentMatches.slice(0, 10).map((m: any, idx: number) => (
                    <div
                      key={m.id || idx}
                      className="flex items-center justify-between font-mono"
                    >
                      <span>{m.user_genotype}</span>
                      <Badge
                        variant={m.is_risk ? 'red' : 'green'}
                        value={m.is_risk ? '风险' : '正常'}
                      />
                      <span className="text-gray-400">
                        评分 {Number(m.risk_score || 0).toFixed(2)}
                      </span>
                    </div>
                  ))}
                  {currentMatches.length > 10 && (
                    <div className="text-gray-400 text-center">
                      ... 还有 {currentMatches.length - 10} 个
                    </div>
                  )}
                </div>
              </div>
            )}

            <div className="flex justify-between">
              <Button variant="ghost" onClick={() => setStep(2)}>
                <ChevronLeft className="w-4 h-4" />
                上一步
              </Button>
            </div>
          </div>
        </Card>
      )}

      {/* Step 4: 报告 */}
      {step === 4 && (
        <div className="space-y-6">
          <Card title="Step 4 · 风险评估报告">
            <RiskScoreChart
              assessment={currentAssessment}
              matches={currentMatches}
              loading={scoreMutation.isPending}
            />
          </Card>

          <Card title="LLM 解读 + 生活建议">
            <div className="space-y-4">
              <div className="flex items-center gap-2 flex-wrap">
                <Button
                  size="sm"
                  loading={interpretMutation.isPending}
                  disabled={!currentAssessment || interpretMutation.isPending}
                  onClick={() => currentAssessment && interpretMutation.mutate(currentAssessment.id)}
                >
                  <Sparkles className="w-4 h-4" />
                  生成 LLM 解读
                </Button>
                <Button
                  size="sm"
                  variant="secondary"
                  loading={recMutation.isPending}
                  disabled={!currentAssessment || recMutation.isPending}
                  onClick={() => currentAssessment && recMutation.mutate(currentAssessment.id)}
                >
                  生成生活建议
                </Button>
              </div>

              <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
                <InterpretationReport
                  interpretation={interpretation}
                  loading={interpretMutation.isPending}
                />
                <RecommendationList
                  recommendations={recommendations}
                  loading={recMutation.isPending}
                />
              </div>
            </div>
          </Card>

          <Card title="个性化治疗推荐">
            <div className="space-y-4">
              <Button
                size="sm"
                loading={treatmentMutation.isPending}
                disabled={!selectedGenome || treatmentMutation.isPending}
                onClick={handleGenerateTreatment}
              >
                <Sparkles className="w-4 h-4" />
                生成治疗推荐
              </Button>
              <PersonalizedTreatmentCard
                data={treatmentData}
                loading={treatmentMutation.isPending}
              />
            </div>
          </Card>

          {/* 疾病相关分析联动 — 个人基因组 ↔ 项目靶点/分子/对接/筛选 */}
          <Card>
            <div className="space-y-4">
              <div className="flex items-center justify-between">
                <h3 className="font-semibold flex items-center gap-2">
                  <Link2 className="w-4 h-4 text-primary-600" />
                  疾病相关分析联动
                  <span className="text-xs font-normal text-gray-500">
                    个人基因组风险变异 ↔ 项目已发现的靶点
                  </span>
                </h3>
              </div>

              <div className="bg-blue-50 border border-blue-200 rounded p-3 text-xs text-blue-800">
                本节将您的基因组风险位点与当前项目
                {currentProject?.name ? `「${currentProject.name}」` : ''} 已发现的
                {projectTargets.length} 个靶点进行交叉比对，
                帮您快速跳转到分子设计、对接、筛选等下一步分析模块。
              </div>

              {/* 匹配到的项目靶点 */}
              <div>
                <div className="text-sm font-medium text-gray-700 mb-2">
                  您的风险变异与项目靶点匹配情况
                  <span className="ml-2 text-xs text-gray-500">
                    （共 {linkedTargets.length} 个匹配 / {projectTargets.length} 个项目靶点）
                  </span>
                </div>
                {linkedTargets.length === 0 ? (
                  <div className="text-center py-6 text-xs text-gray-400 border border-dashed rounded">
                    {currentMatches.length === 0
                      ? '请先在「Step 3 · AI 分析」中完成基因型匹配'
                      : '您的风险变异基因暂未在当前项目靶点中找到匹配项'}
                  </div>
                ) : (
                  <div className="space-y-2">
                    {linkedTargets.map((t) => (
                      <div
                        key={t.id}
                        className="border border-green-200 bg-gradient-to-r from-green-50/60 to-emerald-50/40 rounded-lg p-3"
                      >
                        <div className="flex items-start justify-between gap-3 flex-wrap">
                          <div className="flex-1 min-w-0">
                            <div className="flex items-center gap-2 flex-wrap">
                              <Badge variant="green" value="风险匹配" />
                              <span className="font-bold text-gray-900">
                                {t.gene_symbol}
                              </span>
                              <span className="text-xs text-gray-600">
                                {t.gene_name || ''}
                              </span>
                            </div>
                            <div className="text-xs text-gray-700 mt-1">
                              您的基因型：
                              <span className="font-mono font-bold text-red-700">
                                {t.user_risk_genotype || '—'}
                              </span>
                              {t.user_rs_id && (
                                <span className="ml-2 text-gray-500">({t.user_rs_id})</span>
                              )}
                              {t.user_risk_score != null && (
                                <span className="ml-2 text-gray-500">
                                  风险评分 {Number(t.user_risk_score).toFixed(2)}
                                </span>
                              )}
                            </div>
                            <div className="text-xs text-gray-500 mt-1">
                              靶点置信度：
                              {t.confidence_score != null
                                ? `${(t.confidence_score * 100).toFixed(1)}%`
                                : '—'}
                              {t.evidence_grade && ` · 证据等级 ${t.evidence_grade}`}
                            </div>
                          </div>
                          <div className="flex items-center gap-1 flex-wrap">
                            <button
                              onClick={() =>
                                router.push(`/workbench/targets?selected=${t.id}`)
                              }
                              className="flex items-center gap-1 px-2 py-1 text-xs bg-white border border-gray-300 rounded hover:border-primary-400 hover:bg-primary-50"
                            >
                              <TargetIcon className="w-3 h-3" />
                              靶点详情
                            </button>
                            <button
                              onClick={() =>
                                router.push(`/workbench/molecules?target_id=${t.id}`)
                              }
                              className="flex items-center gap-1 px-2 py-1 text-xs bg-white border border-gray-300 rounded hover:border-primary-400 hover:bg-primary-50"
                            >
                              <Pill className="w-3 h-3" />
                              分子库
                            </button>
                            <button
                              onClick={() =>
                                router.push(`/workbench/docking?target_id=${t.id}`)
                              }
                              className="flex items-center gap-1 px-2 py-1 text-xs bg-white border border-gray-300 rounded hover:border-primary-400 hover:bg-primary-50"
                            >
                              <Combine className="w-3 h-3" />
                              分子对接
                            </button>
                            <button
                              onClick={() =>
                                router.push(`/workbench/screening?target_id=${t.id}`)
                              }
                              className="flex items-center gap-1 px-2 py-1 text-xs bg-white border border-gray-300 rounded hover:border-primary-400 hover:bg-primary-50"
                            >
                              <Filter className="w-3 h-3" />
                              双上下文筛选
                            </button>
                          </div>
                        </div>
                      </div>
                    ))}
                  </div>
                )}
              </div>

              {/* 未被项目覆盖的风险基因 — 提示研究空白 */}
              {uncoveredRiskGenes.length > 0 && (
                <div>
                  <div className="text-sm font-medium text-amber-700 mb-2 flex items-center gap-1">
                    <Sparkles className="w-4 h-4" />
                    未被项目覆盖的风险基因
                    <span className="text-xs font-normal text-gray-500">
                      （可能的新靶点机会）
                    </span>
                  </div>
                  <div className="flex flex-wrap gap-2">
                    {uncoveredRiskGenes.map((g, i) => (
                      <div
                        key={i}
                        className="px-2 py-1 bg-amber-50 border border-amber-200 rounded text-xs"
                      >
                        <span className="font-bold text-amber-800">{g.gene_symbol}</span>
                        <span className="ml-1 text-gray-500 font-mono">
                          {g.rsid}
                        </span>
                        <span className="ml-1 text-red-600 font-mono">
                          {g.user_genotype}
                        </span>
                      </div>
                    ))}
                  </div>
                  <button
                    onClick={() =>
                      router.push(
                        `/workbench/targets?genes=${uncoveredRiskGenes
                          .map((g) => g.gene_symbol)
                          .join(',')}`
                      )
                    }
                    className="mt-3 flex items-center gap-1 text-xs text-primary-600 hover:text-primary-700"
                  >
                    前往靶点发现模块探索这些基因
                    <ArrowRight className="w-3 h-3" />
                  </button>
                </div>
              )}
            </div>
          </Card>

          <div className="flex justify-between">
            <Button variant="ghost" onClick={() => setStep(3)}>
              <ChevronLeft className="w-4 h-4" />
              上一步
            </Button>
            <Button
              onClick={() => {
                setSelectedGenome(null);
                setStoreGenomeId(null);
                setSelectedTraitIds([]);
                setActiveTraitId(null);
                setCurrentAssessment(null);
                setInterpretation(null);
                setRecommendations([]);
                setTreatmentData(null);
                setCurrentMatches([]);
                setStep(1);
              }}
            >
              开始新一次分析
            </Button>
          </div>
        </div>
      )}

      {/* 历史评估抽屉 */}
      <AssessmentHistory
        genomeId={selectedGenome?.id || null}
        open={historyOpen}
        onClose={() => setHistoryOpen(false)}
        onSelect={handleSelectHistory}
      />
    </div>
  );
}
