/**
 * Agent 工作台 REST API 客户端
 *
 * 对应后端 app/api/v1/endpoints/agent.py 的 8 个 REST 端点。
 * 设计来源：2026-07-18-agent-functional-design.md §6
 */
import { api } from './client';
import type { AgentSession, AgentTask, ToolInfo } from '@/types/agent';

// ========== 会话 ==========

export interface SessionCreatePayload {
  title?: string;
  project_id?: string;
}

export interface SessionListParams {
  page?: number;
  page_size?: number;
  include_archived?: boolean;
}

export const createSession = (data: SessionCreatePayload = {}) =>
  api.post('/agent/sessions', data).then((r) => r.data as AgentSession);

export const listSessions = (params: SessionListParams = {}) =>
  api.get('/agent/sessions', { params }).then((r) => r.data as { items: AgentSession[]; total: number; page: number; page_size: number });

export const getSession = (sessionId: string) =>
  api.get(`/agent/sessions/${sessionId}`).then((r) => r.data as AgentSession);

export const archiveSession = (sessionId: string) =>
  api.delete(`/agent/sessions/${sessionId}`).then((r) => r.data as { archived: boolean; session_id: string });

// ========== 对话 ==========

export interface ChatPayload {
  session_id: string;
  message: string;
  project_id?: string;
  tier?: 'fast_screen' | 'deep_insight';
}

export interface ChatResp {
  task_id: string;
  session_id: string;
  status: string;
}

export const sendChat = (data: ChatPayload) =>
  api.post('/agent/chat', data).then((r) => r.data as ChatResp);

// ========== 任务 ==========

export const getTask = (taskId: string) =>
  api.get(`/agent/tasks/${taskId}`).then((r) => r.data as AgentTask);

export const cancelTask = (taskId: string) =>
  api.post(`/agent/tasks/${taskId}/cancel`).then((r) => r.data as { cancelled: boolean; task_id: string });

// ========== 工具 ==========

export const listTools = () =>
  api.get('/agent/tools').then((r) => r.data as { tools: ToolInfo[]; total: number });
