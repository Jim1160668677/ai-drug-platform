'use client';

import { useState } from 'react';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import {
  listValidations,
  createValidation,
  recordResult,
  applyFeedback,
  TASK_TYPE_LABELS,
  TASK_TYPE_ICONS,
  STATUS_LABELS,
  STATUS_COLORS,
  STATUS_COLUMN,
  CONCLUSION_LABELS,
  type ValidationTask,
  type ValidationTaskType,
  type ValidationConclusion,
} from '@/lib/api';
import { useAppStore } from '@/lib/store';
import { ClipboardCheck, Plus, X, FlaskConical, CheckCircle2, XCircle, HelpCircle } from 'lucide-react';

type ColumnKey = 'todo' | 'doing' | 'validated' | 'refuted' | 'unclear';

const COLUMNS: { key: ColumnKey; label: string; accent: string }[] = [
  { key: 'todo', label: '待验证', accent: 'border-slate-400' },
  { key: 'doing', label: '进行中', accent: 'border-amber-400' },
  { key: 'validated', label: '已验证', accent: 'border-green-500' },
  { key: 'refuted', label: '已证伪', accent: 'border-red-500' },
  { key: 'unclear', label: '不确定', accent: 'border-slate-300' },
];

const TASK_TYPE_OPTIONS = Object.keys(TASK_TYPE_LABELS) as ValidationTaskType[];
const CONCLUSION_OPTIONS: ValidationConclusion[] = ['validated', 'refuted', 'inconclusive'];

export default function ValidationsPage() {
  const { currentProject } = useAppStore();
  const projectId = currentProject?.id;
  const [showCreate, setShowCreate] = useState(false);
  const [activeTaskId, setActiveTaskId] = useState<string | null>(null);

  return (
    <div className="space-y-4">
      <div className="flex items-start justify-between">
        <div>
          <h1 className="text-2xl font-bold flex items-center gap-2">
            <ClipboardCheck className="w-6 h-6 text-primary-600" />
            干湿闭环验证
          </h1>
          <p className="text-sm text-slate-500 mt-1">
            把 AI 假设提交到湿实验验证（敲降/过表达/结合/细胞活力/动物/毒理），
            结果回写触发模型置信度反馈：validated +0.1 / refuted -0.2 / inconclusive 不变
          </p>
        </div>
        <button
          onClick={() => setShowCreate(true)}
          disabled={!projectId}
          className="flex items-center gap-1 px-3 py-1.5 text-sm bg-primary-600 text-white rounded hover:bg-primary-700 disabled:opacity-50"
        >
          <Plus className="w-4 h-4" />
          新建验证任务
        </button>
      </div>

      {!projectId && (
        <div className="px-3 py-2 text-sm bg-amber-50 text-amber-700 border border-amber-200 rounded">
          请先在项目页选择一个项目，再创建验证任务。
        </div>
      )}

      <KanbanBoard projectId={projectId} onRecordResult={setActiveTaskId} />

      {showCreate && projectId && (
        <CreateTaskModal projectId={projectId} onClose={() => setShowCreate(false)} />
      )}
      {activeTaskId && (
        <RecordResultModal taskId={activeTaskId} onClose={() => setActiveTaskId(null)} />
      )}
    </div>
  );
}

// ========== Kanban 看板 ==========

function KanbanBoard({
  projectId,
  onRecordResult,
}: {
  projectId?: string;
  onRecordResult: (taskId: string) => void;
}) {
  const { data, isLoading } = useQuery({
    queryKey: ['validations', projectId],
    queryFn: () => listValidations({ project_id: projectId, page_size: 100 }),
    enabled: !!projectId,
  });

  const tasks: ValidationTask[] = data?.data ?? [];

  return (
    <div className="grid grid-cols-5 gap-3">
      {COLUMNS.map((col) => {
        const colTasks = tasks.filter((t) => STATUS_COLUMN[t.status] === col.key);
        return (
          <div key={col.key} className={`rounded-lg border-t-4 ${col.accent} bg-slate-50 min-h-[200px]`}>
            <div className="px-3 py-2 text-sm font-medium text-slate-700 flex items-center justify-between">
              <span>{col.label}</span>
              <span className="text-xs text-slate-400">{colTasks.length}</span>
            </div>
            <div className="px-2 pb-2 space-y-2">
              {isLoading && colTasks.length === 0 && (
                <div className="text-xs text-slate-400 px-2 py-4 text-center">加载中…</div>
              )}
              {!isLoading && colTasks.length === 0 && (
                <div className="text-xs text-slate-400 px-2 py-4 text-center">—</div>
              )}
              {colTasks.map((task) => (
                <TaskCard key={task.id} task={task} onRecordResult={onRecordResult} />
              ))}
            </div>
          </div>
        );
      })}
    </div>
  );
}

function TaskCard({
  task,
  onRecordResult,
}: {
  task: ValidationTask;
  onRecordResult: (taskId: string) => void;
}) {
  const queryClient = useQueryClient();
  const [applying, setApplying] = useState(false);
  const [feedback, setFeedback] = useState<string | null>(null);

  const feedbackMutation = useMutation({
    mutationFn: () => applyFeedback(task.id),
    onSuccess: (res) => {
      const before = res.target_confidence_before;
      const after = res.target_confidence_after;
      if (res.skipped) {
        setFeedback('已应用过反馈，跳过');
      } else if (before !== null && after !== null) {
        setFeedback(`靶点置信度 ${before} → ${after}`);
      } else {
        setFeedback('反馈已应用');
      }
      queryClient.invalidateQueries({ queryKey: ['validations'] });
    },
    onSettled: () => setApplying(false),
  });

  const canRecordResult =
    task.status === 'submitted' || task.status === 'in_progress' || task.status === 'awaiting_result';
  const canApplyFeedback =
    !!task.conclusion && !task.feedback_applied;

  return (
    <div className="bg-white rounded-md border border-slate-200 p-3 text-xs space-y-2 shadow-sm">
      <div className="flex items-start justify-between">
        <div className="font-medium text-slate-800 line-clamp-2">
          <span className="mr-1">{TASK_TYPE_ICONS[task.task_type]}</span>
          {task.hypothesis}
        </div>
        <span className={`px-1.5 py-0.5 rounded text-[10px] border whitespace-nowrap ${STATUS_COLORS[task.status]}`}>
          {STATUS_LABELS[task.status]}
        </span>
      </div>

      {task.prediction && (
        <div className="text-slate-500">
          <span className="text-slate-400">预测：</span>
          {task.prediction}
        </div>
      )}

      {task.actual_result && (
        <div className="text-slate-600 bg-slate-50 rounded p-1.5">
          <span className="text-slate-400">实测：</span>
          {task.actual_result}
        </div>
      )}

      {task.conclusion && (
        <div className="text-slate-600">
          <span className="text-slate-400">结论：</span>
          <span className="font-medium">{CONCLUSION_LABELS[task.conclusion]}</span>
        </div>
      )}

      <div className="flex flex-wrap gap-1 pt-1">
        {canRecordResult && (
          <button
            onClick={() => onRecordResult(task.id)}
            className="px-2 py-1 text-[11px] bg-blue-50 text-blue-700 rounded hover:bg-blue-100"
          >
            记录结果
          </button>
        )}
        {canApplyFeedback && (
          <button
            onClick={() => {
              setApplying(true);
              feedbackMutation.mutate();
            }}
            disabled={applying}
            className="px-2 py-1 text-[11px] bg-green-50 text-green-700 rounded hover:bg-green-100 disabled:opacity-50"
          >
            {applying ? '应用中…' : '应用反馈'}
          </button>
        )}
        {task.feedback_applied && (
          <span className="px-2 py-1 text-[11px] text-green-600 inline-flex items-center gap-1">
            <CheckCircle2 className="w-3 h-3" />
            反馈已应用
          </span>
        )}
      </div>

      {feedback && (
        <div className="text-[11px] text-green-700 bg-green-50 rounded px-2 py-1">{feedback}</div>
      )}
    </div>
  );
}

// ========== 创建任务 Modal ==========

function CreateTaskModal({ projectId, onClose }: { projectId: string; onClose: () => void }) {
  const queryClient = useQueryClient();
  const [form, setForm] = useState({
    task_type: 'target_knockdown' as ValidationTaskType,
    hypothesis: '',
    prediction: '',
    target_id: '',
    molecule_id: '',
  });

  const createMutation = useMutation({
    mutationFn: () =>
      createValidation({
        project_id: projectId,
        task_type: form.task_type,
        hypothesis: form.hypothesis.trim(),
        prediction: form.prediction.trim() || undefined,
        target_id: form.target_id.trim() || undefined,
        molecule_id: form.molecule_id.trim() || undefined,
      }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['validations'] });
      onClose();
    },
  });

  return (
    <Modal onClose={onClose} title="新建验证任务">
      <div className="space-y-3">
        <Field label="验证类型 *">
          <select
            value={form.task_type}
            onChange={(e) => setForm({ ...form, task_type: e.target.value as ValidationTaskType })}
            className="w-full px-3 py-1.5 text-sm border rounded"
          >
            {TASK_TYPE_OPTIONS.map((t) => (
              <option key={t} value={t}>
                {TASK_TYPE_ICONS[t]} {TASK_TYPE_LABELS[t]}
              </option>
            ))}
          </select>
        </Field>

        <Field label="验证假设 *（要验证的科学命题）">
          <textarea
            value={form.hypothesis}
            onChange={(e) => setForm({ ...form, hypothesis: e.target.value })}
            placeholder="例如：EGFR 敲降后 A549 细胞活力下降 >30%"
            rows={3}
            className="w-full px-3 py-1.5 text-sm border rounded"
          />
        </Field>

        <Field label="AI 预期结果（可选）">
          <input
            type="text"
            value={form.prediction}
            onChange={(e) => setForm({ ...form, prediction: e.target.value })}
            placeholder="例如：细胞活力下降至 65%"
            className="w-full px-3 py-1.5 text-sm border rounded"
          />
        </Field>

        <div className="grid grid-cols-2 gap-3">
          <Field label="靶点 ID（可选）">
            <input
              type="text"
              value={form.target_id}
              onChange={(e) => setForm({ ...form, target_id: e.target.value })}
              placeholder="target UUID"
              className="w-full px-3 py-1.5 text-sm border rounded font-mono text-xs"
            />
          </Field>
          <Field label="分子 ID（可选）">
            <input
              type="text"
              value={form.molecule_id}
              onChange={(e) => setForm({ ...form, molecule_id: e.target.value })}
              placeholder="molecule UUID"
              className="w-full px-3 py-1.5 text-sm border rounded font-mono text-xs"
            />
          </Field>
        </div>

        {createMutation.isError && (
          <div className="text-xs text-red-600 bg-red-50 px-2 py-1 rounded">
            创建失败：{(createMutation.error as Error)?.message || '未知错误'}
          </div>
        )}

        <div className="flex justify-end gap-2 pt-2">
          <button onClick={onClose} className="px-3 py-1.5 text-sm border rounded">
            取消
          </button>
          <button
            onClick={() => createMutation.mutate()}
            disabled={!form.hypothesis.trim() || createMutation.isPending}
            className="px-3 py-1.5 text-sm bg-primary-600 text-white rounded hover:bg-primary-700 disabled:opacity-50"
          >
            {createMutation.isPending ? '提交中…' : '提交'}
          </button>
        </div>
      </div>
    </Modal>
  );
}

// ========== 记录结果 Modal ==========

function RecordResultModal({ taskId, onClose }: { taskId: string; onClose: () => void }) {
  const queryClient = useQueryClient();
  const [actualResult, setActualResult] = useState('');
  const [conclusion, setConclusion] = useState<ValidationConclusion>('validated');
  const [nextAction, setNextAction] = useState('');

  const recordMutation = useMutation({
    mutationFn: () =>
      recordResult(taskId, {
        actual_result: actualResult.trim(),
        conclusion,
        next_action: nextAction.trim() || undefined,
      }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['validations'] });
      onClose();
    },
  });

  return (
    <Modal onClose={onClose} title="记录实验结果">
      <div className="space-y-3">
        <Field label="实验实测结果 *">
          <textarea
            value={actualResult}
            onChange={(e) => setActualResult(e.target.value)}
            placeholder="例如：细胞活力下降至 60%（预测 65%，方向一致）"
            rows={3}
            className="w-full px-3 py-1.5 text-sm border rounded"
          />
        </Field>

        <Field label="结论 *（决定后续反馈方向）">
          <div className="grid grid-cols-3 gap-2">
            {CONCLUSION_OPTIONS.map((c) => {
              const Icon =
                c === 'validated' ? CheckCircle2 : c === 'refuted' ? XCircle : HelpCircle;
              const color =
                c === 'validated'
                  ? 'border-green-500 bg-green-50 text-green-700'
                  : c === 'refuted'
                    ? 'border-red-500 bg-red-50 text-red-700'
                    : 'border-slate-400 bg-slate-50 text-slate-700';
              return (
                <button
                  key={c}
                  onClick={() => setConclusion(c)}
                  className={`px-2 py-2 text-xs border rounded flex flex-col items-center gap-1 ${
                    conclusion === c ? color : 'border-slate-200 text-slate-500 hover:bg-slate-50'
                  }`}
                >
                  <Icon className="w-4 h-4" />
                  {CONCLUSION_LABELS[c]}
                </button>
              );
            })}
          </div>
          <p className="text-[11px] text-slate-400 mt-1">
            validated → 靶点置信度 +0.1；refuted → -0.2；inconclusive → 不调整
          </p>
        </Field>

        <Field label="下一步行动（可选）">
          <input
            type="text"
            value={nextAction}
            onChange={(e) => setNextAction(e.target.value)}
            placeholder="例如：进入 PDX 动物模型验证"
            className="w-full px-3 py-1.5 text-sm border rounded"
          />
        </Field>

        {recordMutation.isError && (
          <div className="text-xs text-red-600 bg-red-50 px-2 py-1 rounded">
            记录失败：{(recordMutation.error as Error)?.message || '未知错误'}
          </div>
        )}

        <div className="flex justify-end gap-2 pt-2">
          <button onClick={onClose} className="px-3 py-1.5 text-sm border rounded">
            取消
          </button>
          <button
            onClick={() => recordMutation.mutate()}
            disabled={!actualResult.trim() || recordMutation.isPending}
            className="px-3 py-1.5 text-sm bg-primary-600 text-white rounded hover:bg-primary-700 disabled:opacity-50"
          >
            {recordMutation.isPending ? '保存中…' : '保存结果'}
          </button>
        </div>
      </div>
    </Modal>
  );
}

// ========== 通用组件 ==========

function Field({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div>
      <label className="block text-xs font-medium text-slate-600 mb-1">{label}</label>
      {children}
    </div>
  );
}

function Modal({
  title,
  onClose,
  children,
}: {
  title: string;
  onClose: () => void;
  children: React.ReactNode;
}) {
  return (
    <div className="fixed inset-0 bg-black/40 flex items-center justify-center z-50" onClick={onClose}>
      <div
        className="bg-white rounded-lg shadow-xl w-full max-w-lg mx-4 max-h-[90vh] overflow-y-auto"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="flex items-center justify-between px-4 py-3 border-b">
          <h3 className="text-sm font-semibold flex items-center gap-2">
            <FlaskConical className="w-4 h-4 text-primary-600" />
            {title}
          </h3>
          <button onClick={onClose} className="text-slate-400 hover:text-slate-600">
            <X className="w-4 h-4" />
          </button>
        </div>
        <div className="p-4">{children}</div>
      </div>
    </div>
  );
}
