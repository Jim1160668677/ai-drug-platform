'use client';

import { useState, useEffect, useCallback } from 'react';
import { useQuery, useMutation } from '@tanstack/react-query';
import { createRun, getCases, generateResearchGoal, getComprehensiveTemplate } from '@/lib/api';
import { useAppStore } from '@/lib/store';
import { toast } from '@/lib/notification';
import type { CaseInfo, RunResponse, GenerateGoalResult, ComprehensiveTemplate } from '@/types/coscientist';
import {
  Loader2, Sparkles, FlaskConical, Database, Info,
  Wand2, ChevronDown, ChevronUp, Layers, Zap, Brain, Target, ClipboardList,
} from 'lucide-react';

const CASE_ICONS: Record<string, typeof FlaskConical> = {
  custom: Sparkles,
  comprehensive: Layers,
};

// 配置预设
const CONFIG_PRESETS = [
  { key: 'quick', label: '快速探索', maxRounds: 2, initialCount: 5, icon: Zap, desc: '2轮 / 5假设' },
  { key: 'standard', label: '标准研究', maxRounds: 3, initialCount: 5, icon: Sparkles, desc: '3轮 / 5假设' },
  { key: 'deep', label: '深度研究', maxRounds: 5, initialCount: 8, icon: Brain, desc: '5轮 / 8假设' },
] as const;

interface RunCreatorProps {
  onCreated?: (run: RunResponse) => void;
  suggestedGoal?: string;
}

export default function RunCreator({ onCreated, suggestedGoal }: RunCreatorProps) {
  const [researchGoal, setResearchGoal] = useState('');
  const [caseType, setCaseType] = useState<string>('custom');
  const [maxRounds, setMaxRounds] = useState(3);
  const [initialCount, setInitialCount] = useState(5);
  const [showAdvanced, setShowAdvanced] = useState(false);
  const [aiTopic, setAiTopic] = useState('');
  const [aiResult, setAiResult] = useState<GenerateGoalResult | null>(null);
  const [selectedPreset, setSelectedPreset] = useState<string>('standard');

  const { currentProject } = useAppStore();

  // 上下文感知：当外部传入建议目标且当前输入为空时自动填充
  useEffect(() => {
    if (suggestedGoal && researchGoal.trim().length === 0) {
      setResearchGoal(suggestedGoal);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [suggestedGoal]);

  const { data: casesData } = useQuery({
    queryKey: ['coscientist-cases'],
    queryFn: getCases,
  });
  const cases: CaseInfo[] = casesData?.cases ?? [];

  const { data: comprehensiveData } = useQuery({
    queryKey: ['coscientist-comprehensive-template'],
    queryFn: getComprehensiveTemplate,
    staleTime: 5 * 60 * 1000,
  });
  const comprehensive: ComprehensiveTemplate | undefined = comprehensiveData;

  // AI 生成研究目标
  const aiMutation = useMutation({
    mutationFn: () =>
      generateResearchGoal({
        topic: aiTopic,
        project_id: currentProject?.id,
        case_type: caseType !== 'custom' ? caseType : undefined,
      }),
    onSuccess: (data: GenerateGoalResult) => {
      setAiResult(data);
      setResearchGoal(data.research_goal);
      // 应用 AI 建议的参数
      if (data.suggested_max_rounds) setMaxRounds(data.suggested_max_rounds);
      if (data.suggested_initial_count) setInitialCount(data.suggested_initial_count);
      if (data.suggested_case_type) setCaseType(data.suggested_case_type);
      toast.success('AI 生成完成', '已自动填充研究目标和推荐参数');
    },
    onError: (err: any) => {
      toast.error('AI 生成失败', err?.response?.data?.error?.message ?? '请稍后重试或手动输入');
    },
  });

  const mutation = useMutation({
    mutationFn: () =>
      createRun({
        research_goal: researchGoal,
        project_id: currentProject?.id,
        case_type: caseType === 'custom' || caseType === 'comprehensive' ? undefined : (caseType as any),
        max_rounds: maxRounds,
        initial_hypothesis_count: initialCount,
      }),
    onSuccess: (data) => {
      onCreated?.(data as RunResponse);
      setResearchGoal('');
      setAiResult(null);
      setAiTopic('');
      toast.success('运行已启动', 'Co-Scientist 正在后台推理');
    },
    onError: (err: any) => {
      toast.error('启动失败', err?.response?.data?.error?.message ?? '未知错误');
    },
  });

  const handleSubmit = () => {
    if (researchGoal.trim().length < 10) return;
    mutation.mutate();
  };

  const handleCaseSelect = useCallback((type: string, c?: CaseInfo | ComprehensiveTemplate) => {
    setCaseType(type);
    if (c) {
      const goal = 'research_goal_template' in c ? c.research_goal_template : '';
      if (goal && researchGoal.trim().length < 10) {
        setResearchGoal(goal);
      }
    }
  }, [researchGoal]);

  const handlePresetSelect = (presetKey: string) => {
    setSelectedPreset(presetKey);
    const preset = CONFIG_PRESETS.find((p) => p.key === presetKey);
    if (preset) {
      setMaxRounds(preset.maxRounds);
      setInitialCount(preset.initialCount);
    }
  };

  // 当手动调整参数时取消预设选中
  useEffect(() => {
    const matched = CONFIG_PRESETS.find((p) => p.maxRounds === maxRounds && p.initialCount === initialCount);
    setSelectedPreset(matched ? matched.key : '');
  }, [maxRounds, initialCount]);

  // 构建模板卡片列表
  const templateCards: Array<{ type: string; name: string; desc: string; icon: typeof Sparkles; data?: any }> = [
    { type: 'custom', name: '自定义', desc: '自由输入研究目标', icon: Sparkles },
    ...(comprehensive ? [{
      type: 'comprehensive',
      name: comprehensive.name,
      desc: comprehensive.description,
      icon: Layers,
      data: comprehensive,
    }] : []),
    ...cases.map((c) => ({
      type: c.case_type,
      name: c.name,
      desc: c.description,
      icon: CASE_ICONS[c.case_type] ?? Sparkles,
      data: c,
    })),
  ];

  const selectedTemplate = templateCards.find((t) => t.type === caseType);

  return (
    <div className="space-y-4">
      <h2 className="text-lg font-semibold flex items-center gap-2">
        <Sparkles className="w-5 h-5 text-indigo-500" />
        启动 Co-Scientist 科学推理
      </h2>

      {/* 项目关联提示 */}
      {currentProject ? (
        <div className="p-3 bg-indigo-50 border border-indigo-200 rounded-lg flex items-start gap-2">
          <Database className="w-4 h-4 text-indigo-600 flex-shrink-0 mt-0.5" />
          <div className="text-xs text-indigo-800">
            <div className="font-medium">已关联项目：{currentProject.name}</div>
            <div className="mt-0.5 text-indigo-600">
              推理引擎将自动整合该项目的靶点、分子、实验结果、数据集等前期分析数据进行综合推理
            </div>
          </div>
        </div>
      ) : (
        <div className="p-3 bg-amber-50 border border-amber-200 rounded-lg flex items-start gap-2">
          <Info className="w-4 h-4 text-amber-600 flex-shrink-0 mt-0.5" />
          <div className="text-xs text-amber-800">
            未关联项目。请在顶部选择一个项目，Co-Scientist 将基于项目前期数据进行针对性推理。
          </div>
        </div>
      )}

      {/* AI 智能生成研究目标 */}
      <div className="p-4 bg-gradient-to-br from-purple-50 to-indigo-50 border border-purple-200 rounded-lg space-y-3">
        <div className="flex items-center gap-2">
          <Wand2 className="w-4 h-4 text-purple-600" />
          <span className="text-sm font-medium text-purple-800">AI 智能生成研究目标</span>
        </div>
        <div className="flex gap-2">
          <input
            type="text"
            value={aiTopic}
            onChange={(e) => setAiTopic(e.target.value)}
            placeholder="输入研究主题，如：急性髓系白血病药物重定位、肝纤维化靶点发现..."
            className="flex-1 px-3 py-2 text-sm border border-purple-200 rounded-lg bg-white focus:ring-2 focus:ring-purple-400 focus:border-transparent"
            maxLength={500}
            onKeyDown={(e) => {
              if (e.key === 'Enter' && aiTopic.trim().length >= 2 && !aiMutation.isPending) {
                aiMutation.mutate();
              }
            }}
          />
          <button
            onClick={() => aiMutation.mutate()}
            disabled={aiTopic.trim().length < 2 || aiMutation.isPending}
            className="px-4 py-2 text-sm font-medium text-white bg-purple-600 rounded-lg flex items-center gap-1.5 disabled:opacity-50 disabled:cursor-not-allowed hover:bg-purple-700 transition whitespace-nowrap"
          >
            {aiMutation.isPending ? (
              <>
                <Loader2 className="w-4 h-4 animate-spin" />
                生成中...
              </>
            ) : (
              <>
                <Wand2 className="w-4 h-4" />
                AI 生成
              </>
            )}
          </button>
        </div>

        {/* AI 生成结果展示 */}
        {aiResult && (
          <div className="space-y-2 pt-2 border-t border-purple-200">
            {aiResult.framework.length > 0 && (
              <div>
                <div className="flex items-center gap-1 text-xs font-medium text-purple-700 mb-1">
                  <Layers className="w-3 h-3" /> 研究框架
                </div>
                <div className="flex flex-wrap gap-1.5">
                  {aiResult.framework.map((f, i) => (
                    <span key={i} className="px-2 py-0.5 text-xs bg-white border border-purple-200 rounded text-purple-700">
                      {f}
                    </span>
                  ))}
                </div>
              </div>
            )}
            {aiResult.key_questions.length > 0 && (
              <div>
                <div className="flex items-center gap-1 text-xs font-medium text-purple-700 mb-1">
                  <Target className="w-3 h-3" /> 关键科学问题
                </div>
                <ul className="space-y-0.5">
                  {aiResult.key_questions.map((q, i) => (
                    <li key={i} className="text-xs text-gray-600 flex items-start gap-1">
                      <span className="text-purple-400 mt-0.5">•</span> {q}
                    </li>
                  ))}
                </ul>
              </div>
            )}
            {aiResult.content_suggestions.length > 0 && (
              <div>
                <div className="flex items-center gap-1 text-xs font-medium text-purple-700 mb-1">
                  <ClipboardList className="w-3 h-3" /> 内容建议
                </div>
                <ul className="space-y-0.5">
                  {aiResult.content_suggestions.map((s, i) => (
                    <li key={i} className="text-xs text-gray-600 flex items-start gap-1">
                      <span className="text-purple-400 mt-0.5">→</span> {s}
                    </li>
                  ))}
                </ul>
              </div>
            )}
          </div>
        )}
      </div>

      {/* 研究模板选择 — 卡片式 */}
      <div>
        <label className="text-sm font-medium text-gray-600 mb-2 block">
          研究模板（可选，快速填充研究目标和参数）
        </label>
        <div className="grid grid-cols-2 gap-2">
          {templateCards.map((card) => {
            const Icon = card.icon;
            const isSelected = caseType === card.type;
            return (
              <button
                key={card.type}
                onClick={() => handleCaseSelect(card.type, card.data)}
                className={`p-3 text-left rounded-lg border transition ${
                  isSelected
                    ? 'border-indigo-500 bg-indigo-50 ring-1 ring-indigo-200'
                    : 'border-gray-200 bg-white hover:border-gray-300 hover:bg-gray-50'
                }`}
              >
                <div className="flex items-center gap-2 mb-1">
                  <Icon className={`w-4 h-4 ${isSelected ? 'text-indigo-600' : 'text-gray-400'}`} />
                  <span className={`text-sm font-medium ${isSelected ? 'text-indigo-700' : 'text-gray-700'}`}>
                    {card.name}
                  </span>
                </div>
                <p className="text-xs text-gray-500 line-clamp-2">{card.desc}</p>
              </button>
            );
          })}
        </div>
      </div>

      {/* 综合模板子模板信息 */}
      {caseType === 'comprehensive' && comprehensive?.sub_templates && (
        <div className="p-3 bg-blue-50 border border-blue-200 rounded-lg">
          <div className="text-xs font-medium text-blue-700 mb-1.5">包含子模板：</div>
          <div className="flex flex-wrap gap-1.5">
            {comprehensive.sub_templates.map((st) => (
              <span key={st.case_type} className="px-2 py-0.5 text-xs bg-white border border-blue-200 rounded text-blue-600">
                {st.name}
              </span>
            ))}
          </div>
          {comprehensive.framework && (
            <div className="mt-2">
              <div className="text-xs font-medium text-blue-700 mb-1">研究框架：</div>
              <div className="flex flex-wrap gap-1">
                {comprehensive.framework.map((f, i) => (
                  <span key={i} className="text-xs text-gray-600">{i + 1}. {f}</span>
                ))}
              </div>
            </div>
          )}
        </div>
      )}

      {/* 研究目标 */}
      <div>
        <label className="text-sm font-medium text-gray-600 mb-2 block">
          研究目标 <span className="text-gray-400">（至少 10 字符）</span>
        </label>
        <textarea
          value={researchGoal}
          onChange={(e) => setResearchGoal(e.target.value)}
          placeholder="描述你的科学研究目标，例如：发现可用于急性髓系白血病治疗的已批准药物..."
          className="w-full p-3 border rounded-lg resize-y min-h-[100px] text-sm focus:ring-2 focus:ring-indigo-500 focus:border-transparent"
          maxLength={5000}
        />
        <div className="text-xs text-gray-400 mt-1 flex justify-between">
          <span>{researchGoal.length} / 5000</span>
          {researchGoal && (
            <button
              onClick={() => { setResearchGoal(''); setAiResult(null); }}
              className="text-gray-400 hover:text-red-500"
            >
              清空
            </button>
          )}
        </div>
      </div>

      {/* 高级配置 — 可折叠 */}
      <div className="border border-gray-200 rounded-lg overflow-hidden">
        <button
          onClick={() => setShowAdvanced(!showAdvanced)}
          className="w-full flex items-center justify-between p-3 text-sm font-medium text-gray-600 hover:bg-gray-50 transition"
        >
          <span className="flex items-center gap-2">
            <Sparkles className="w-4 h-4 text-indigo-400" />
            高级配置
            <span className="text-xs text-gray-400 font-normal">
              （轮数: {maxRounds} / 假设: {initialCount}）
            </span>
          </span>
          {showAdvanced ? <ChevronUp className="w-4 h-4" /> : <ChevronDown className="w-4 h-4" />}
        </button>

        {showAdvanced && (
          <div className="p-3 pt-0 space-y-4 border-t border-gray-100">
            {/* 配置预设 */}
            <div>
              <label className="text-xs font-medium text-gray-500 mb-2 block">配置预设</label>
              <div className="grid grid-cols-3 gap-2">
                {CONFIG_PRESETS.map((preset) => {
                  const Icon = preset.icon;
                  const isActive = selectedPreset === preset.key;
                  return (
                    <button
                      key={preset.key}
                      onClick={() => handlePresetSelect(preset.key)}
                      className={`p-2 rounded-lg border text-center transition ${
                        isActive
                          ? 'border-indigo-500 bg-indigo-50'
                          : 'border-gray-200 bg-white hover:border-gray-300'
                      }`}
                    >
                      <Icon className={`w-4 h-4 mx-auto mb-1 ${isActive ? 'text-indigo-600' : 'text-gray-400'}`} />
                      <div className={`text-xs font-medium ${isActive ? 'text-indigo-700' : 'text-gray-600'}`}>
                        {preset.label}
                      </div>
                      <div className="text-[10px] text-gray-400">{preset.desc}</div>
                    </button>
                  );
                })}
              </div>
            </div>

            {/* 参数滑块 */}
            <div className="grid grid-cols-2 gap-4">
              <div>
                <label className="text-sm font-medium text-gray-600 mb-2 block">
                  最大迭代轮数：<span className="text-indigo-600">{maxRounds}</span>
                </label>
                <input
                  type="range"
                  min={1}
                  max={10}
                  value={maxRounds}
                  onChange={(e) => setMaxRounds(Number(e.target.value))}
                  className="w-full"
                />
                <div className="flex justify-between text-[10px] text-gray-400 mt-0.5">
                  <span>1</span><span>5</span><span>10</span>
                </div>
              </div>
              <div>
                <label className="text-sm font-medium text-gray-600 mb-2 block">
                  初始假设数量：<span className="text-indigo-600">{initialCount}</span>
                </label>
                <input
                  type="range"
                  min={3}
                  max={10}
                  value={initialCount}
                  onChange={(e) => setInitialCount(Number(e.target.value))}
                  className="w-full"
                />
                <div className="flex justify-between text-[10px] text-gray-400 mt-0.5">
                  <span>3</span><span>6</span><span>10</span>
                </div>
              </div>
            </div>
          </div>
        )}
      </div>

      {/* 提交 */}
      <button
        onClick={handleSubmit}
        disabled={researchGoal.trim().length < 10 || mutation.isPending}
        className="w-full py-2.5 px-4 bg-indigo-600 text-white rounded-lg font-medium flex items-center justify-center gap-2 disabled:opacity-50 disabled:cursor-not-allowed hover:bg-indigo-700 transition"
      >
        {mutation.isPending ? (
          <>
            <Loader2 className="w-4 h-4 animate-spin" />
            启动中...
          </>
        ) : (
          <>
            <Sparkles className="w-4 h-4" />
            启动科学推理
          </>
        )}
      </button>
    </div>
  );
}
