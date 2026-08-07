import { api } from './client';

// ========== 类型定义 ==========

/** 验证任务类型 — 直接对应评委「抑制/过表达是否影响疾病」的湿实验验证 */
export type ValidationTaskType =
  | 'target_knockdown' // 靶点敲降（siRNA/shRNA/CRISPR）
  | 'target_overexpression' // 靶点过表达
  | 'binding_assay' // 结合实验（SPR/ITC）
  | 'cell_viability' // 细胞活力
  | 'animal_study' // 动物模型（PDX）
  | 'toxicity_study'; // 毒理实验

/** 验证任务状态 — 记录结果后收敛为 conclusion 值 */
export type ValidationTaskStatus =
  | 'draft'
  | 'submitted'
  | 'in_progress'
  | 'awaiting_result'
  | 'validated'
  | 'refuted'
  | 'inconclusive';

/** 验证结论 — 与 FeedbackLoop 反馈规则联动 */
export type ValidationConclusion = 'validated' | 'refuted' | 'inconclusive';

export interface ValidationTask {
  id: string;
  project_id: string;
  target_id: string | null;
  molecule_id: string | null;
  treatment_id: string | null;
  task_type: ValidationTaskType;
  hypothesis: string;
  prediction: string | null;
  status: ValidationTaskStatus;
  experiment_id: string | null;
  partner_id: string | null;
  submitted_at: string | null;
  result_received_at: string | null;
  actual_result: string | null;
  conclusion: ValidationConclusion | null;
  feedback_applied: boolean;
  next_action: string | null;
  notes: string | null;
  created_at: string | null;
}

export interface ValidationFeedbackResult {
  task_id: string;
  conclusion: ValidationConclusion;
  target_id: string | null;
  target_confidence_before: number | null;
  target_confidence_after: number | null;
  molecule_id: string | null;
  molecule_status: string | null;
  feedback_applied: boolean;
  skipped?: boolean;
  message?: string;
}

// ========== API 调用 ==========

export interface ListValidationsParams {
  project_id?: string;
  status?: ValidationTaskStatus;
  task_type?: ValidationTaskType;
  page?: number;
  page_size?: number;
}

export const listValidations = (params: ListValidationsParams = {}) =>
  api
    .get('/validations', {
      params: {
        project_id: params.project_id,
        status: params.status,
        task_type: params.task_type,
        page: params.page ?? 1,
        page_size: params.page_size ?? 50,
      },
    })
    .then((r) => r.data);

export const getValidation = (id: string) =>
  api.get(`/validations/${id}`).then((r) => r.data as ValidationTask);

export interface CreateValidationInput {
  project_id: string;
  target_id?: string;
  molecule_id?: string;
  treatment_id?: string;
  task_type: ValidationTaskType;
  hypothesis: string;
  prediction?: string;
  partner_id?: string;
  notes?: string;
}

export const createValidation = (data: CreateValidationInput) =>
  api.post('/validations', data).then((r) => r.data as ValidationTask);

export interface UpdateValidationInput {
  hypothesis?: string;
  prediction?: string;
  notes?: string;
  next_action?: string;
  partner_id?: string;
}

export const updateValidation = (id: string, data: UpdateValidationInput) =>
  api.patch(`/validations/${id}`, data).then((r) => r.data as ValidationTask);

export const linkExperiment = (taskId: string, experimentId: string) =>
  api
    .post(`/validations/${taskId}/link-experiment`, { experiment_id: experimentId })
    .then((r) => r.data as ValidationTask);

export interface RecordResultInput {
  actual_result: string;
  conclusion: ValidationConclusion;
  next_action?: string;
}

export const recordResult = (taskId: string, data: RecordResultInput) =>
  api.post(`/validations/${taskId}/result`, data).then((r) => r.data as ValidationTask);

export const applyFeedback = (taskId: string) =>
  api
    .post(`/validations/${taskId}/apply-feedback`)
    .then((r) => r.data as ValidationFeedbackResult);

// ========== 常量标签 ==========

export const TASK_TYPE_LABELS: Record<ValidationTaskType, string> = {
  target_knockdown: '靶点敲降',
  target_overexpression: '靶点过表达',
  binding_assay: '结合实验',
  cell_viability: '细胞活力',
  animal_study: '动物模型',
  toxicity_study: '毒理实验',
};

export const TASK_TYPE_ICONS: Record<ValidationTaskType, string> = {
  target_knockdown: '🧬',
  target_overexpression: '⬆️',
  binding_assay: '🔗',
  cell_viability: '🧫',
  animal_study: '🐭',
  toxicity_study: '☠️',
};

/** 把 status 映射到 Kanban 列 */
export const STATUS_COLUMN: Record<ValidationTaskStatus, 'todo' | 'doing' | 'validated' | 'refuted' | 'unclear'> = {
  draft: 'todo',
  submitted: 'todo',
  in_progress: 'doing',
  awaiting_result: 'doing',
  validated: 'validated',
  refuted: 'refuted',
  inconclusive: 'unclear',
};

export const STATUS_LABELS: Record<ValidationTaskStatus, string> = {
  draft: '草稿',
  submitted: '已提交',
  in_progress: '进行中',
  awaiting_result: '等待结果',
  validated: '已验证',
  refuted: '已证伪',
  inconclusive: '不确定',
};

export const STATUS_COLORS: Record<ValidationTaskStatus, string> = {
  draft: 'bg-slate-100 text-slate-600 border-slate-300',
  submitted: 'bg-blue-100 text-blue-700 border-blue-300',
  in_progress: 'bg-amber-100 text-amber-700 border-amber-300',
  awaiting_result: 'bg-amber-100 text-amber-700 border-amber-300',
  validated: 'bg-green-100 text-green-700 border-green-300',
  refuted: 'bg-red-100 text-red-700 border-red-300',
  inconclusive: 'bg-slate-100 text-slate-600 border-slate-300',
};

export const CONCLUSION_LABELS: Record<ValidationConclusion, string> = {
  validated: '假设被验证',
  refuted: '假设被证伪',
  inconclusive: '结论不明确',
};
