/**
 * Agent 工作台类型定义
 *
 * 对应后端 app/schemas/agent.py 与 app/services/agent/progress.py 的事件协议。
 * 设计来源：2026-07-18-agent-functional-design.md §4/§6
 */

// ========== 会话与任务 ==========

export type SessionStatus = 'active' | 'archived' | 'deleted';

export type TaskStatus =
  | 'pending'
  | 'planning'
  | 'running'
  | 'awaiting_confirmation'
  | 'completed'
  | 'failed'
  | 'cancelled';

export const TERMINAL_TASK_STATUSES: ReadonlySet<TaskStatus> = new Set([
  'completed',
  'failed',
  'cancelled',
]);

export interface AgentSession {
  id: string;
  user_id: string;
  project_id?: string;
  title: string;
  status: SessionStatus;
  message_count: number;
  last_message_at?: string;
  created_at: string;
  updated_at: string;
}

export interface TokenUsage {
  prompt: number;
  completion: number;
  total: number;
}

export interface AgentTask {
  id: string;
  session_id: string;
  user_id: string;
  project_id?: string;
  query: string;
  plan?: Plan;
  status: TaskStatus;
  result?: {
    answer?: string;
    steps?: Array<Record<string, unknown>>;
    token_usage?: TokenUsage;
    cost_usd?: number;
    duration_sec?: number;
  };
  error?: string;
  started_at?: string;
  completed_at?: string;
  token_usage?: TokenUsage;
  cost_usd?: number;
}

// ========== 任务规划 ==========

export interface PlanStep {
  id: string;
  tool: string;
  args: Record<string, unknown>;
  depends_on: string[];
  description?: string;
}

export interface Plan {
  steps: PlanStep[];
  parallel_layers: string[][];
  reasoning?: string;
}

// ========== 工具调用 ==========

export interface ToolCall {
  step: number;
  tool: string;
  args: Record<string, unknown>;
  thought?: string;
}

export interface ToolResult {
  step: number;
  tool: string;
  success: boolean;
  data?: unknown;
  error?: string;
  duration_ms?: number;
  /** 缓存命中标记（后端从 LLM 缓存或工具结果缓存复用时返回） */
  cache_hit?: boolean;
  /** 服务端渲染提示：{type: chart|table|stats, payload} */
  display?: { type?: string; payload?: unknown };
}

export interface ToolInfo {
  name: string;
  description: string;
  parameters: Record<string, unknown>;
  side_effects: boolean;
  required_role: string;
}

// ========== WebSocket 事件协议 ==========

export type WSEventType =
  | 'connected'
  | 'task_started'
  | 'plan'
  | 'thought'
  | 'tool_call'
  | 'tool_result'
  | 'confirmation_required'
  | 'final_response'
  | 'error'
  | 'task_completed'
  | 'task_cancelled'
  | 'token'
  | 'ping'
  | 'pong'
  | 'progress_snapshot'
  | 'not_found'
  | 'force_close'
  | 'unsubscribed';

export interface WSEvent<T = unknown> {
  type: WSEventType;
  task_id: string;
  timestamp: string;
  payload: T;
}

// 各类事件的 payload 类型
export interface ThoughtPayload {
  thought: string;
  step: number;
  max_steps: number;
}

/** 流式 token 事件 payload（LLM 边生成边推送） */
export interface TokenPayload {
  token: string;
  step?: number;
}

export interface PlanPayload extends Plan {}

export interface ToolCallPayload extends ToolCall {}

export interface ToolResultPayload extends ToolResult {}

export interface FinalResponsePayload {
  answer: string;
  references?: Array<{ title?: string; source?: string }>;
}

export interface ConfirmationRequiredPayload {
  task_id: string;
  tool: string;
  args: Record<string, unknown>;
}

export interface ErrorPayload {
  error: string;
  error_code?: string;
}

export interface TaskCompletedPayload {
  answer?: string;
  plan?: Plan;
  steps?: Array<Record<string, unknown>>;
  token_usage?: TokenUsage;
  cost_usd?: number;
  duration_sec?: number;
  status: TaskStatus;
}

// ========== 客户端发送给服务端的消息 ==========

export type WSClientMessageType =
  | 'subscribe'
  | 'unsubscribe'
  | 'cancel'
  | 'confirm'
  | 'ping';

export interface WSClientMessage<T = unknown> {
  type: WSClientMessageType;
  task_id?: string;
  payload?: T;
}

// ========== 前端聚合的消息项（用于 MessageList 渲染） ==========

export interface AgentMessage {
  id: string;
  role: 'user' | 'assistant' | 'tool' | 'system';
  content: string;
  toolCalls?: ToolCall[];
  toolResults?: ToolResult[];
  thought?: string;
  step?: number;
  timestamp: string;
  /** 标记为流式响应（LLM 边生成边显示），结构化事件到达时会被清理 */
  isStreaming?: boolean;
  /** 任务元数据（仅 assistant 最终消息有） */
  meta?: {
    task_id?: string;
    status?: TaskStatus;
    token_usage?: TokenUsage;
    cost_usd?: number;
    duration_sec?: number;
  };
}
