/**
 * API 响应类型定义 — 与后端统一信封对齐
 *
 * 后端信封定义：app/schemas/common.py
 * - ApiResponse<T>      { success, data, meta: { request_id, duration_ms } }
 * - PagedResponse<T>    { success, data: [...], meta: { request_id, duration_ms, pagination } }
 * - ErrorResponse        { success: false, error: { code, message, details, request_id } }
 */

// ========== 统一信封 ==========

export interface ResponseMeta {
  request_id?: string;
  duration_ms?: number;
}

export interface ApiResponse<T = unknown> {
  success: boolean;
  data: T;
  meta?: ResponseMeta;
}

export interface PagedMeta extends ResponseMeta {
  pagination: {
    page: number;
    page_size: number;
    total: number;
    total_pages: number;
  };
}

export interface PagedResponse<T = unknown> {
  success: boolean;
  data: T[];
  meta?: PagedMeta;
}

export interface ErrorDetail {
  code: string;
  message: string;
  details?: Record<string, unknown>;
  request_id?: string;
}

export interface ErrorResponse {
  success: false;
  error: ErrorDetail;
}

// ========== 业务实体 ==========

export interface User {
  id: string;
  email: string;
  name: string;
  role: 'founder' | 'chief' | 'researcher' | 'doctor' | 'engineer';
  organization?: string;
  is_active: boolean;
  created_at: string;
}

export interface Project {
  id: string;
  name: string;
  patient_pseudonym?: string;
  cancer_type?: string;
  stage?: string;
  description?: string;
  status: string;
  owner_id: string;
  created_at: string;
}

export interface Dataset {
  id: string;
  project_id: string;
  name: string;
  data_type: string;
  source?: string;
  file_format?: string;
  file_size?: number;
  parse_status: 'pending' | 'parsing' | 'completed' | 'failed';
  quality_metrics?: Record<string, unknown>;
  parsed_summary?: Record<string, unknown>;
  created_at: string;
}

export interface Target {
  id: string;
  project_id: string;
  gene_symbol: string;
  gene_name?: string;
  evidence_grade: string;
  confidence_score?: number;
  source?: string;
  annotation?: Record<string, unknown>;
  pathway?: Record<string, unknown>;
  approved_drugs?: unknown[];
  evidence_chain?: Record<string, unknown>;
  analysis_tier?: string;
  created_at: string;
}

export interface Molecule {
  id: string;
  smiles: string;
  name?: string;
  chembl_id?: string;
  molecular_weight?: number;
  logp?: number;
  properties?: Record<string, unknown>;
  docking_result?: Record<string, unknown>;
  is_approved?: boolean;
  designed_by?: string;
}

export interface Hypothesis {
  id: string;
  project_id: string;
  name: string;
  description?: string;
  mechanism?: string;
  strategy?: string;
  status: string;
  analysis_result?: Record<string, unknown>;
  target_list?: string[];
  forced_deep_analysis?: boolean;
  created_at: string;
}

export interface Experiment {
  id: string;
  name?: string;
  exp_type?: string;
  status?: string;
  feedback_applied?: boolean;
  success?: boolean;
  lab_source?: string;
  project_id?: string;
  target_id?: string;
}

// ========== LLM 配置 ==========

export interface LLMConfig {
  id: string;
  name: string;
  provider: string;
  access_mode: string;
  upstream_protocol: string;
  base_url: string;
  api_key_masked: string;
  test_model: string;
  fast_model?: string;
  deep_model?: string;
  temperature: number;
  max_tokens: number;
  timeout_sec: number;
  is_active: boolean;
  description?: string;
  last_test_at?: string;
  last_test_success?: boolean;
  last_test_message?: string;
  created_at: string;
  updated_at: string;
}

// ========== 反馈协作 ==========

export interface FeedbackSummary {
  project_id?: string;
  total_experiments: number;
  feedback_applied: number;
  successful: number;
  feedback_rate: number;
  success_rate: number;
  by_status: Record<string, number>;
  by_target: Record<string, number>;
}

export interface BiasDetectionResult {
  target_symbol: string;
  sample_count: number;
  mape?: number;
  mae?: number;
  rmse?: number;
  threshold: number;
  has_bias: boolean;
}

// ========== 联邦学习 ==========

export interface FederatedJob {
  id: string;
  project_id?: string;
  status: 'pending' | 'running' | 'completed' | 'failed';
  min_clients?: number;
  rounds?: number;
  current_round?: number;
  participated_clients?: number;
  created_at?: string;
  updated_at?: string;
}

// ========== 隐私计算 ==========

export interface PrivacyDomain {
  id: string;
  name: string;
  data_schema?: Record<string, unknown>;
  privacy_params?: Record<string, unknown>;
  status?: string;
  created_at?: string;
}

// ========== 疗效监测 ==========

export interface EfficacyRecord {
  id: string;
  project_id?: string;
  target_id?: string;
  treatment_id?: string;
  orr?: number; // Objective Response Rate
  dcr?: number; // Disease Control Rate
  recist_response?: string;
  follow_up_days?: number;
  adverse_events?: unknown[];
  created_at?: string;
}

export interface EfficacySummary {
  project_id?: string;
  total_records: number;
  overall_orr: number;
  overall_dcr: number;
  median_pfs_days?: number;
  median_os_days?: number;
  by_target?: Record<string, { orr: number; dcr: number; count: number }>;
}

// ========== 聊天历史 ==========

export interface ChatHistoryItem {
  id: string;
  message: string;
  project_id?: string;
  tier?: string;
  model?: string;
  cost_usd?: number;
  duration_sec?: number;
  created_at?: string;
}

// ========== WebSocket 任务进度 ==========

export interface TaskProgress {
  task_id: string;
  percent: number;
  message: string;
  status: 'pending' | 'running' | 'completed' | 'failed';
  updated_at: string;
}
