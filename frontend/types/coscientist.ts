/**
 * Co-Scientist 类型定义 — 与后端 app/schemas/coscientist.py 对齐
 *
 * 多智能体科学推理引擎的类型契约：
 * - 运行管理（RunCreate/RunResponse）
 * - 假设排名（RankedHypothesis）
 * - 辩论日志（DebateLog）
 * - 进化树（EvolutionNode/Edge）
 * - 专家反馈（FeedbackPayload）
 * - WebSocket 事件（CoScientistWSEvent）
 */

// ========== 运行状态枚举 ==========

export type RunStatus =
  | 'pending'
  | 'running'
  | 'awaiting_feedback'
  | 'completed'
  | 'failed'
  | 'cancelled';

export type RunPhase =
  | 'generation'
  | 'proximity'
  | 'reflection'
  | 'debate'
  | 'ranking'
  | 'evolution'
  | 'meta_review';

// 验证案例（aml/liver_fibrosis/amr）已删除，仅保留 custom
export type CaseType = 'custom';

export type FeedbackType =
  | 'constraint'
  | 'approval'
  | 'rejection'
  | 'new_evidence'
  | 'directional'
  | 'veto'
  | 'elo_adjustment'
  | 'refinement';

// ========== 运行 ==========

export interface RunCreate {
  research_goal: string;
  project_id?: string;
  case_type?: CaseType;
  max_rounds?: number;
  initial_hypothesis_count?: number;
  config?: Record<string, unknown>;
}

export interface RunResponse {
  id: string;
  user_id: string;
  project_id?: string | null;
  session_id?: string | null;
  research_goal: string;
  case_type?: string | null; // string 而非 CaseType，兼容历史记录中的旧 case_type 值
  status: RunStatus;
  current_round: number;
  max_rounds: number;
  current_phase?: RunPhase | null;
  config?: Record<string, unknown> | null;
  final_rankings?: Record<string, unknown> | null;
  meta_review?: string | null;
  expert_feedback?: Array<Record<string, unknown>> | null;
  total_cost_usd?: number | null;
  duration_sec?: number | null;
  started_at?: string | null;
  completed_at?: string | null;
  error_message?: string | null;
  created_at: string;
  updated_at: string;
}

export interface RunListResponse {
  items: RunResponse[];
  total: number;
  page: number;
  page_size: number;
}

// ========== 假设排名 ==========

export interface RankedHypothesis {
  id: string;
  name: string;
  description?: string | null;
  mechanism?: string | null;
  elo_score: number;
  novelty_score?: number | null;
  plausibility_score?: number | null;
  testability_score?: number | null;
  safety_score?: number | null;
  rank?: number | null;
  evolution_strategy?: string | null;
  parent_ids?: string[] | null;
  critique_summary?: string | null;
  status: string;
  experimental_elo_adjustment?: number | null;
  experimental_validation_count?: number | null;
}

export interface RankingsResponse {
  run_id: string;
  round_num: number;
  rankings: RankedHypothesis[];
  total_hypotheses: number;
}

// ========== 辩论日志 ==========

export interface DebateLog {
  id: string;
  run_id: string;
  hypothesis_id: string;
  round_num: number;
  proponent_argument: string;
  opponent_argument: string;
  judge_assessment?: string | null;
  consensus_score?: number | null;
  mechanism_agreed?: boolean | null;
  refined_hypothesis?: string | null;
  cost_usd?: number | null;
  created_at: string;
}

export interface DebateListResponse {
  run_id: string;
  debates: DebateLog[];
  total: number;
}

// ========== 进化树 ==========

export interface EvolutionNode {
  hypothesis_id: string;
  name: string;
  evolution_strategy: string;
  parent_ids: string[];
  elo_score: number;
  round_num: number;
  rank?: number | null;
}

export interface EvolutionEdge {
  from_id: string;
  to_id: string;
  strategy: string;
}

export interface EvolutionTreeResponse {
  run_id: string;
  nodes: EvolutionNode[];
  edges: EvolutionEdge[];
  total_rounds: number;
}

// ========== Meta-review ==========

export interface MetaReviewResponse {
  run_id: string;
  meta_review: string;
  final_rankings?: Record<string, unknown> | null;
  total_cost_usd?: number | null;
  duration_sec?: number | null;
  completed_at?: string | null;
}

// ========== 专家反馈 ==========

export interface FeedbackPayload {
  feedback_text: string;
  feedback_type: FeedbackType;
  target_hypothesis_id?: string;
}

export interface FeedbackResponse {
  accepted: boolean;
  message: string;
  applied_round?: number | null;
  parsed_constraints?: Record<string, unknown> | null;
}

// ========== 案例 ==========

export interface CaseInfo {
  case_type: CaseType;
  name: string;
  description: string;
  research_goal_template: string;
  expected_benchmarks: Record<string, unknown>;
}

export interface CaseListResponse {
  cases: CaseInfo[];
}

// ========== AI 智能生成研究目标 ==========

export interface GenerateGoalResult {
  research_goal: string;
  suggested_case_type: string | null;
  suggested_max_rounds: number;
  suggested_initial_count: number;
  framework: string[];
  key_questions: string[];
  content_suggestions: string[];
}

// ========== 综合性研究模板 ==========

export interface ComprehensiveTemplate {
  case_type: string;
  name: string;
  description: string;
  research_goal_template: string;
  expected_benchmarks: Record<string, any>;
  sub_templates: Array<{ case_type: string; name: string; description: string }>;
  framework: string[];
  config_presets: Record<string, { max_rounds: number; initial_count: number; description: string }>;
}


// ========== Agent 活动 ==========

export interface AgentActivity {
  agent_name: string;
  status: 'idle' | 'running' | 'completed' | 'failed';
  current_task?: string | null;
  started_at?: string | null;
  completed_at?: string | null;
  token_usage?: Record<string, number> | null;
  cost_usd?: number | null;
  error?: string | null;
}

export interface AgentActivityFeedResponse {
  run_id: string;
  agents: AgentActivity[];
  current_phase?: RunPhase | null;
  current_round: number;
}

// ========== 进度 ==========

export interface ProgressSnapshot {
  run_id: string;
  status: RunStatus;
  current_round: number;
  max_rounds: number;
  current_phase?: RunPhase | null;
  recent_events: WSEventPayload[];
  total_cost_usd?: number;
  total_tokens?: number;
}

// ========== WebSocket 事件 ==========

export interface WSEventPayload {
  type: string;
  run_id: string;
  timestamp: string;
  payload: Record<string, unknown>;
}

export interface WSClientMessage {
  type: 'subscribe' | 'unsubscribe' | 'feedback' | 'cancel' | 'ping';
  run_id?: string;
  payload?: Record<string, unknown>;
}
