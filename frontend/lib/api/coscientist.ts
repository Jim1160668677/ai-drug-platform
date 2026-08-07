/**
 * Co-Scientist API 客户端 — 多智能体科学推理引擎
 *
 * 后端端点：app/api/v1/endpoints/coscientist.py
 * - 13 REST 端点（运行管理、假设、排名、辩论、进度、案例）
 * - 1 WebSocket 端点（实时进度推送）
 */
import { api } from './client';
import { WS_BASE } from './ws';
import type {
  RunCreate,
  RunResponse,
  RunListResponse,
  RankingsResponse,
  DebateListResponse,
  EvolutionTreeResponse,
  MetaReviewResponse,
  FeedbackPayload,
  FeedbackResponse,
  CaseListResponse,
  AgentActivityFeedResponse,
  ProgressSnapshot,
  RankedHypothesis,
  WSClientMessage,
  WSEventPayload,
  GenerateGoalResult,
  ComprehensiveTemplate,
} from '@/types/coscientist';

// ========== 运行管理 ==========

/** POST /coscientist/runs — 创建 Co-Scientist 运行 */
export const createRun = (payload: RunCreate) =>
  api.post('/coscientist/runs', payload).then((r) => r.data?.data ?? r.data);

/** GET /coscientist/runs — 列出运行 */
export const listRuns = (params?: { page?: number; page_size?: number; status?: string }) =>
  api.get('/coscientist/runs', { params }).then((r) => r.data?.data ?? r.data) as Promise<RunListResponse>;

/** GET /coscientist/runs/{id} — 运行详情 */
export const getRun = (runId: string) =>
  api.get(`/coscientist/runs/${runId}`).then((r) => r.data?.data ?? r.data) as Promise<RunResponse>;

/** POST /coscientist/runs/{id}/cancel — 取消运行 */
export const cancelRun = (runId: string) =>
  api.post(`/coscientist/runs/${runId}/cancel`).then((r) => r.data?.data ?? r.data);

/** DELETE /coscientist/runs/{id} — 删除运行 */
export const deleteRun = (runId: string) =>
  api.delete(`/coscientist/runs/${runId}`).then((r) => r.data?.data ?? r.data);

// ========== 假设与排名 ==========

/** GET /coscientist/runs/{id}/hypotheses — 假设列表 */
export const getHypotheses = (runId: string) =>
  api.get(`/coscientist/runs/${runId}/hypotheses`).then((r) => r.data?.data ?? r.data) as Promise<RankedHypothesis[]>;

/** GET /coscientist/runs/{id}/hypotheses/{hid} — 假设详情 */
export const getHypothesisDetail = (runId: string, hypId: string) =>
  api.get(`/coscientist/runs/${runId}/hypotheses/${hypId}`).then((r) => r.data?.data ?? r.data) as Promise<RankedHypothesis>;

/** GET /coscientist/runs/{id}/rankings — 排名 */
export const getRankings = (runId: string) =>
  api.get(`/coscientist/runs/${runId}/rankings`).then((r) => r.data?.data ?? r.data) as Promise<RankingsResponse>;

// ========== 辩论日志 ==========

/** GET /coscientist/runs/{id}/debates — 辩论日志 */
export const getDebates = (runId: string) =>
  api.get(`/coscientist/runs/${runId}/debates`).then((r) => r.data?.data ?? r.data) as Promise<DebateListResponse>;

// ========== 进化树 ==========

/** GET /coscientist/runs/{id}/evolution-tree — 进化树 */
export const getEvolutionTree = (runId: string) =>
  api.get(`/coscientist/runs/${runId}/evolution-tree`).then((r) => r.data?.data ?? r.data) as Promise<EvolutionTreeResponse>;

// ========== 进度与统计 ==========

/** GET /coscientist/runs/{id}/progress — 进度快照 */
export const getProgress = (runId: string) =>
  api.get(`/coscientist/runs/${runId}/progress`).then((r) => r.data?.data ?? r.data) as Promise<ProgressSnapshot>;

/** GET /coscientist/runs/{id}/stats — Agent 活动统计 */
export const getAgentStats = (runId: string) =>
  api.get(`/coscientist/runs/${runId}/stats`).then((r) => r.data?.data ?? r.data) as Promise<AgentActivityFeedResponse>;

// ========== Meta-review ==========

/** GET /coscientist/runs/{id}/meta-review — 元评审报告 */
export const getMetaReview = (runId: string) =>
  api.get(`/coscientist/runs/${runId}/meta-review`).then((r) => r.data?.data ?? r.data) as Promise<MetaReviewResponse>;

// ========== 专家反馈 ==========

/** POST /coscientist/runs/{id}/feedback — 提交专家反馈 */
export const submitFeedback = (runId: string, payload: FeedbackPayload) =>
  api.post(`/coscientist/runs/${runId}/feedback`, payload).then((r) => r.data?.data ?? r.data) as Promise<FeedbackResponse>;

// ========== 案例 ==========

/** GET /coscientist/cases — 案例列表 */
export const getCases = () =>
  api.get('/coscientist/cases').then((r) => r.data?.data ?? r.data) as Promise<CaseListResponse>;


// ========== AI 智能生成研究目标 ==========

/** POST /coscientist/generate-goal — AI 智能生成研究目标 */
export const generateResearchGoal = (payload: { topic: string; project_id?: string; case_type?: string }) =>
  api.post('/coscientist/generate-goal', payload).then((r) => r.data?.data ?? r.data) as Promise<GenerateGoalResult>;

// ========== 综合性研究模板 ==========

/** GET /coscientist/comprehensive-template — 综合性研究模板 */
export const getComprehensiveTemplate = () =>
  api.get('/coscientist/comprehensive-template').then((r) => r.data?.data ?? r.data) as Promise<ComprehensiveTemplate>;

// ========== WebSocket 实时进度 ==========

export interface CoScientistWSCallbacks {
  onEvent?: (event: WSEventPayload) => void;
  onConnected?: () => void;
  onDisconnected?: () => void;
  onError?: (error: Event) => void;
}

/**
 * CoScientistWebSocket — 运行进度实时推送客户端
 *
 * 端点：/api/v1/coscientist/runs/{run_id}/ws
 *
 * 特性：
 * - 自动重连（指数退避，最多 5 次）
 * - 心跳保活（30 秒 ping）
 * - 支持发送专家反馈和取消运行
 */
export class CoScientistWebSocket {
  private ws: WebSocket | null = null;
  private runId: string;
  private token: string;
  private callbacks: CoScientistWSCallbacks;
  private retryCount = 0;
  private maxRetries = 5;
  private initialRetryDelay = 1000;
  private heartbeatInterval = 30000;
  private retryTimer: ReturnType<typeof setTimeout> | null = null;
  private heartbeatTimer: ReturnType<typeof setInterval> | null = null;
  private disposed = false;

  constructor(runId: string, token: string, callbacks: CoScientistWSCallbacks = {}) {
    this.runId = runId;
    this.token = token;
    this.callbacks = callbacks;
  }

  /** 建立 WebSocket 连接 */
  connect(): void {
    if (this.disposed) return;

    const wsUrl = `${WS_BASE}/coscientist/runs/${this.runId}/ws?token=${encodeURIComponent(this.token)}`;
    try {
      this.ws = new WebSocket(wsUrl);
    } catch (err) {
      console.error('[CoSci-WS] 构造失败:', err);
      this.callbacks.onError?.(new Event('error'));
      return;
    }

    this.ws.onopen = () => {
      this.retryCount = 0;
      this.callbacks.onConnected?.();
      this.startHeartbeat();
    };

    this.ws.onmessage = (event) => {
      try {
        const data: WSEventPayload = JSON.parse(event.data);
        this.callbacks.onEvent?.(data);
      } catch (err) {
        console.warn('[CoSci-WS] 消息解析失败:', err);
      }
    };

    this.ws.onerror = (event) => {
      this.callbacks.onError?.(event);
    };

    this.ws.onclose = () => {
      this.stopHeartbeat();
      this.callbacks.onDisconnected?.();
      if (!this.disposed) {
        this.scheduleReconnect();
      }
    };
  }

  /** 主动断开连接 */
  disconnect(): void {
    this.disposed = true;
    this.stopHeartbeat();
    if (this.retryTimer) {
      clearTimeout(this.retryTimer);
      this.retryTimer = null;
    }
    if (this.ws) {
      this.ws.onclose = null;
      this.ws.onerror = null;
      this.ws.onmessage = null;
      if (this.ws.readyState === WebSocket.OPEN || this.ws.readyState === WebSocket.CONNECTING) {
        this.ws.close();
      }
      this.ws = null;
    }
  }

  /** 发送客户端消息 */
  send(message: WSClientMessage): void {
    if (this.ws && this.ws.readyState === WebSocket.OPEN) {
      try {
        this.ws.send(JSON.stringify(message));
      } catch (err) {
        console.warn('[CoSci-WS] 发送失败:', err);
      }
    }
  }

  /** 提交专家反馈 */
  sendFeedback(feedbackText: string, feedbackType: string, targetHypothesisId?: string): void {
    this.send({
      type: 'feedback',
      run_id: this.runId,
      payload: {
        feedback_text: feedbackText,
        feedback_type: feedbackType,
        target_hypothesis_id: targetHypothesisId,
      },
    });
  }

  /** 取消运行 */
  cancel(): void {
    this.send({ type: 'cancel', run_id: this.runId });
  }

  /** 心跳 */
  private startHeartbeat(): void {
    this.heartbeatTimer = setInterval(() => {
      if (this.ws && this.ws.readyState === WebSocket.OPEN) {
        try {
          this.ws.send(JSON.stringify({ type: 'ping' }));
        } catch {
          // 忽略发送失败
        }
      }
    }, this.heartbeatInterval);
  }

  private stopHeartbeat(): void {
    if (this.heartbeatTimer) {
      clearInterval(this.heartbeatTimer);
      this.heartbeatTimer = null;
    }
  }

  /** 重连（指数退避） */
  private scheduleReconnect(): void {
    if (this.retryCount >= this.maxRetries) {
      console.warn('[CoSci-WS] 超过最大重试次数，停止重连');
      return;
    }
    const delay = this.initialRetryDelay * Math.pow(2, this.retryCount);
    this.retryCount += 1;
    this.retryTimer = setTimeout(() => {
      if (!this.disposed) {
        this.connect();
      }
    }, delay);
  }
}

// ========== Co-Scientist 洞察管理（嵌入式协作层）==========

export interface Insight {
  id: string;
  user_id: string;
  project_id: string | null;
  source_run_id: string | null;
  trigger_event: string | null;
  entity_type: string;
  entity_id: string | null;
  entity_name: string | null;
  insight_type: string;
  title: string;
  summary: string;
  details: Record<string, unknown> | null;
  suggested_action: string | null;
  action_payload: Record<string, unknown> | null;
  status: 'pending' | 'read' | 'accepted' | 'dismissed' | 'expired';
  accepted_entity_id: string | null;
  accepted_at: string | null;
  confidence_score: number | null;
  created_at: string;
}

export interface InsightListResponse {
  items: Insight[];
  total: number;
  page: number;
  page_size: number;
}

/** GET /coscientist/insights — 洞察列表 */
export const listInsights = (params?: {
  project_id?: string;
  entity_type?: string;
  entity_id?: string;
  status?: string;
  page?: number;
  page_size?: number;
}) => api.get<InsightListResponse>('/coscientist/insights', { params }).then(r => r.data);

/** GET /coscientist/insights/pending-count — 待处理数量 */
export const getPendingInsightCount = (projectId?: string) =>
  api.get<{ pending_count: number }>('/coscientist/insights/pending-count', {
    params: projectId ? { project_id: projectId } : {},
  }).then(r => r.data);

/** GET /coscientist/insights/{id} — 洞察详情 */
export const getInsight = (insightId: string) =>
  api.get<Insight>(`/coscientist/insights/${insightId}`).then(r => r.data);

/** POST /coscientist/insights/{id}/accept — 采纳洞察 */
export const acceptInsight = (insightId: string) =>
  api.post(`/coscientist/insights/${insightId}/accept`).then(r => r.data);

/** POST /coscientist/insights/{id}/dismiss — 忽略洞察 */
export const dismissInsight = (insightId: string) =>
  api.post(`/coscientist/insights/${insightId}/dismiss`).then(r => r.data);

/** POST /coscientist/insights/{id}/read — 标记已读 */
export const markInsightRead = (insightId: string) =>
  api.post(`/coscientist/insights/${insightId}/read`).then(r => r.data);

/** POST /coscientist/insights/bulk-read — 批量已读 */
export const bulkMarkInsightsRead = (payload: { project_id?: string; entity_type?: string }) =>
  api.post('/coscientist/insights/bulk-read', payload).then(r => r.data);

// ========== 就地轻推理（异步任务+轮询）==========

export interface QuickReasonRequest {
  project_id?: string;
  entity_type: string;
  entity_id: string;
  entity_name?: string;
  reason_type?: string;
  extra_context?: string;
}

export interface QuickReasonResponse {
  run_id: string;
  trigger_event: string;
  message: string;
  poll_endpoint: string;
}

/** POST /coscientist/quick-reason — 就地轻推理 */
export const quickReason = (payload: QuickReasonRequest) =>
  api.post<QuickReasonResponse>('/coscientist/quick-reason', payload).then(r => r.data);

// ========== 动态研究目标 ==========

export interface SuggestedGoalResponse {
  goal: string;
  page: string | null;
  has_evidence: boolean;
  evidence_length: number;
  suggested_cases: Array<{ case_type: string; reason: string }>;
}

/** GET /coscientist/suggested-goal — 动态生成研究目标 */
export const getSuggestedGoal = (params: { project_id?: string; page?: string }) =>
  api.get<SuggestedGoalResponse>('/coscientist/suggested-goal', { params }).then(r => r.data);

// ========== 假设回写（Promote：将 Top 假设回写到业务实体）==========

/** 回写目标类型 */
export type PromoteTargetType = 'target' | 'molecule' | 'experiment' | 'treatment';

export interface PromoteHypothesisPayload {
  project_id?: string;
  run_id?: string;
  entity_name?: string;
  notes?: string;
  [key: string]: unknown;
}

export interface PromoteResponse {
  id: string;
  target_type: PromoteTargetType;
  source_hypothesis_id: string;
  project_id: string | null;
  entity_id?: string;
  message: string;
}

/** POST /coscientist/runs/{runId}/hypotheses/{hypId}/promote-target — 回写为靶点 */
export const promoteHypothesisToTarget = (
  runId: string,
  hypId: string,
  payload?: PromoteHypothesisPayload,
) =>
  api.post<PromoteResponse>(`/coscientist/runs/${runId}/hypotheses/${hypId}/promote-target`, payload ?? {})
    .then(r => r.data);

/** POST /coscientist/runs/{runId}/hypotheses/{hypId}/promote-molecule — 回写为分子 */
export const promoteHypothesisToMolecule = (
  runId: string,
  hypId: string,
  payload?: PromoteHypothesisPayload,
) =>
  api.post<PromoteResponse>(`/coscientist/runs/${runId}/hypotheses/${hypId}/promote-molecule`, payload ?? {})
    .then(r => r.data);

/** POST /coscientist/runs/{runId}/hypotheses/{hypId}/promote-experiment — 回写为实验 */
export const promoteHypothesisToExperiment = (
  runId: string,
  hypId: string,
  payload?: PromoteHypothesisPayload,
) =>
  api.post<PromoteResponse>(`/coscientist/runs/${runId}/hypotheses/${hypId}/promote-experiment`, payload ?? {})
    .then(r => r.data);

/** POST /coscientist/runs/{runId}/hypotheses/{hypId}/promote-treatment — 回写为治疗方案 */
export const promoteHypothesisToTreatment = (
  runId: string,
  hypId: string,
  payload?: PromoteHypothesisPayload,
) =>
  api.post<PromoteResponse>(`/coscientist/runs/${runId}/hypotheses/${hypId}/promote-treatment`, payload ?? {})
    .then(r => r.data);
