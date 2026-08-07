'use client';

/**
 * PromotePanel — 浮窗内假设回写面板
 *
 * 展示某个 Co-Scientist 运行中的 Top 假设列表，并提供 4 个回写按钮，将假设落地为
 * 业务实体：[→靶点] [→分子] [→实验] [→治疗]
 *
 * - 调用 getHypotheses(runId) 获取假设列表（按 Elo 排序）
 * - 调用 promoteHypothesisToTarget/Molecule/Experiment/Treatment
 * - promote 成功后 toast + invalidateQueries 刷新对应业务页面列表
 *   （targets / molecules / experiments / treatments 列表查询）
 * - 已回写的目标类型显示绿色「已回写」徽章（按假设 + 目标类型维度记录）
 */
import { useState } from 'react';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import {
  getHypotheses,
  promoteHypothesisToTarget,
  promoteHypothesisToMolecule,
  promoteHypothesisToExperiment,
  promoteHypothesisToTreatment,
  scheduleExperiment,
  type ScheduleExperimentPayload,
} from '@/lib/api';
import { useAppStore } from '@/lib/store';
import { toast } from '@/lib/notification';
import type { RankedHypothesis } from '@/types/coscientist';
import {
  Loader2,
  Trophy,
  Target,
  FlaskRound,
  Beaker,
  Pill,
  CheckCircle2,
  FileCode,
  X,
  Play,
} from 'lucide-react';

interface PromotePanelProps {
  /** 运行 ID */
  runId: string;
  /** 项目 ID（可选，缺省从 useAppStore.currentProject 取） */
  projectId?: string;
}

/** 回写目标类型配置 */
const PROMOTE_ACTIONS = [
  {
    key: 'target' as const,
    label: '→靶点',
    icon: Target,
    color: 'text-amber-600 hover:bg-amber-50 hover:border-amber-300',
    invalidateKey: ['targets'],
    successMsg: '已回写为靶点',
    mutate: promoteHypothesisToTarget,
  },
  {
    key: 'molecule' as const,
    label: '→分子',
    icon: FlaskRound,
    color: 'text-blue-600 hover:bg-blue-50 hover:border-blue-300',
    invalidateKey: ['molecules'],
    successMsg: '已回写为分子',
    mutate: promoteHypothesisToMolecule,
  },
  {
    key: 'experiment' as const,
    label: '→实验',
    icon: Beaker,
    color: 'text-green-600 hover:bg-green-50 hover:border-green-300',
    invalidateKey: ['experiments'],
    successMsg: '已回写为实验',
    mutate: promoteHypothesisToExperiment,
  },
  {
    key: 'treatment' as const,
    label: '→治疗',
    icon: Pill,
    color: 'text-purple-600 hover:bg-purple-50 hover:border-purple-300',
    invalidateKey: ['treatments'],
    successMsg: '已回写为治疗方案',
    mutate: promoteHypothesisToTreatment,
  },
];

export default function PromotePanel({ runId, projectId }: PromotePanelProps) {
  const storeProjectId = useAppStore((s) => s.currentProject?.id);
  const effectiveProjectId = projectId ?? storeProjectId;

  const { data: hypotheses, isLoading } = useQuery({
    queryKey: ['coscientist-hypotheses', runId],
    queryFn: () => getHypotheses(runId),
    enabled: !!runId,
    refetchInterval: 8000,
  });

  if (isLoading) {
    return (
      <div className="flex items-center justify-center py-8">
        <Loader2 className="w-5 h-5 animate-spin text-gray-400" />
      </div>
    );
  }

  const list: RankedHypothesis[] = hypotheses ?? [];
  if (list.length === 0) {
    return (
      <div className="text-center py-8 text-gray-400 text-sm">
        暂无假设 — 等待推理生成阶段完成
      </div>
    );
  }

  return (
    <div className="space-y-3">
      <div className="flex items-center gap-2 mb-1">
        <Trophy className="w-4 h-4 text-amber-500" />
        <h3 className="text-sm font-semibold text-gray-700">Top 假设回写</h3>
        <span className="text-xs text-gray-400">共 {list.length} 个</span>
      </div>

      {list.slice(0, 10).map((hyp, idx) => {
        const rank = hyp.rank ?? idx + 1;
        return (
          <PromoteHypothesisItem
            key={hyp.id}
            hypothesis={hyp}
            rank={rank}
            runId={runId}
            projectId={effectiveProjectId}
          />
        );
      })}

      {/* DSL 预览弹窗 */}
      {showDslModal && dslPreview && (
        <DslPreviewModal
          dsl={dslPreview}
          onClose={() => setShowDslModal(false)}
          onRun={() => {
            toast.info('实验调度已提交', '请查看实验列表');
            setShowDslModal(false);
          }}
        />
      )}
    </div>
  );
}

/** DSL 预览弹窗 */
function DslPreviewModal({
  dsl,
  onClose,
  onRun,
}: {
  dsl: Record<string, unknown>;
  onClose: () => void;
  onRun: () => void;
}) {
  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40">
      <div className="bg-white rounded-xl shadow-xl w-full max-w-lg mx-4 max-h-[80vh] overflow-hidden flex flex-col">
        <div className="flex items-center justify-between px-4 py-3 border-b border-gray-100">
          <h3 className="text-sm font-semibold text-gray-800 flex items-center gap-2">
            <FileCode className="w-4 h-4 text-green-600" />
            实验设计 DSL 预览
          </h3>
          <button onClick={onClose} className="text-gray-400 hover:text-gray-600">
            <X className="w-4 h-4" />
          </button>
        </div>
        <div className="flex-1 overflow-auto p-4">
          <pre className="text-xs bg-gray-50 rounded-lg p-3 text-gray-700 whitespace-pre-wrap font-mono">
            {JSON.stringify(dsl, null, 2)}
          </pre>
        </div>
        <div className="flex items-center justify-end gap-2 px-4 py-3 border-t border-gray-100">
          <button
            onClick={onClose}
            className="px-3 py-1.5 text-sm text-gray-600 border border-gray-200 rounded-lg hover:bg-gray-50"
          >
            关闭
          </button>
          <button
            onClick={onRun}
            className="inline-flex items-center gap-1.5 px-3 py-1.5 text-sm font-medium text-white bg-green-600 rounded-lg hover:bg-green-700"
          >
            <Play className="w-3.5 h-3.5" />
            提交调度
          </button>
        </div>
      </div>
    </div>
  );
}

/** 单条假设的回写卡片 */
function PromoteHypothesisItem({
  hypothesis,
  rank,
  runId,
  projectId,
}: {
  hypothesis: RankedHypothesis;
  rank: number;
  runId: string;
  projectId?: string;
}) {
  // 记录已成功回写的目标类型（按假设维度），用于在按钮上显示「已回写」徽章
  const [promoted, setPromoted] = useState<Set<string>>(new Set());

  const markPromoted = (key: string) =>
    setPromoted((prev) => {
      const next = new Set(prev);
      next.add(key);
      return next;
    });

  return (
    <div className="p-3 bg-white border border-gray-200 rounded-lg">
      <div className="flex items-start gap-2 mb-1.5">
        <span className="text-xs font-bold text-gray-400 mt-0.5">#{rank}</span>
        <div className="min-w-0 flex-1">
          <h4 className="text-sm font-semibold text-gray-800 leading-snug">{hypothesis.name}</h4>
          {hypothesis.description && (
            <p className="text-xs text-gray-600 mt-0.5 line-clamp-2">{hypothesis.description}</p>
          )}
        </div>
        <div className="text-right flex-shrink-0">
          <div className="text-sm font-bold text-indigo-600">{hypothesis.elo_score?.toFixed(0) ?? '-'}</div>
          <div className="text-[10px] text-gray-400">Elo</div>
        </div>
      </div>

      {hypothesis.mechanism && (
        <p className="text-[11px] text-gray-500 italic mb-2 line-clamp-2">{hypothesis.mechanism}</p>
      )}

      {/* 4 个回写按钮 */}
      <div className="flex items-center gap-1.5 flex-wrap mt-2">
        {PROMOTE_ACTIONS.map((action) => (
          <PromoteButton
            key={action.key}
            label={action.label}
            icon={action.icon}
            color={action.color}
            invalidateKey={action.invalidateKey}
            successMsg={action.successMsg}
            alreadyPromoted={promoted.has(action.key)}
            onPromoted={() => markPromoted(action.key)}
            onPromote={() =>
              action.mutate(runId, hypothesis.id, {
                project_id: projectId,
                run_id: runId,
                entity_name: hypothesis.name,
              })
            }
          />
        ))}
      </div>
    </div>
  );
}

/** 单个回写按钮（自带 mutation 状态） */
function PromoteButton({
  label,
  icon: Icon,
  color,
  invalidateKey,
  successMsg,
  alreadyPromoted,
  onPromote,
  onPromoted,
}: {
  label: string;
  icon: typeof Target;
  color: string;
  invalidateKey: string[];
  successMsg: string;
  alreadyPromoted: boolean;
  onPromote: () => Promise<unknown>;
  onPromoted?: () => void;
}) {
  const queryClient = useQueryClient();

  const mutation = useMutation({
    mutationFn: onPromote,
    onSuccess: () => {
      toast.success(successMsg, '已刷新对应业务页面');
      // 失效对应业务列表查询，触发刷新
      queryClient.invalidateQueries({ queryKey: invalidateKey });
      onPromoted?.();
    },
    onError: (err: unknown) => {
      const msg = err instanceof Error ? err.message : '请稍后重试';
      toast.error('回写失败', msg);
    },
  });

  if (alreadyPromoted) {
    return (
      <span className="inline-flex items-center gap-1 px-2 py-1 text-[11px] text-green-700 bg-green-50 border border-green-200 rounded">
        <CheckCircle2 className="w-3 h-3" />
        {label}
      </span>
    );
  }

  return (
    <button
      type="button"
      onClick={() => mutation.mutate()}
      disabled={mutation.isPending}
      className={`inline-flex items-center gap-1 px-2 py-1 text-[11px] font-medium border border-gray-200 rounded transition-colors disabled:opacity-50 ${color}`}
    >
      {mutation.isPending ? <Loader2 className="w-3 h-3 animate-spin" /> : <Icon className="w-3 h-3" />}
      {label}
    </button>
  );
}
