/**
 * 统一智能系统（Intelligence）API 客户端
 *
 * 对应后端 app/api/v1/endpoints/intelligence.py 的 22 个端点。
 *
 * 五大功能域：
 *  1. 会话管理（createSession / listSessions / getSession / archiveSession）
 *  2. 统一对话（chat / streamChat / forceMode）— streamChat 使用 fetch + ReadableStream 解析 SSE
 *  3. 上下文与追溯（getContext / getTrace / getTraceTree / getCostBreakdown / getDecisionChain）
 *  4. 证据收集与分析（collectEvidence / collectEntityContext / interpretAnalysis / interpretDataset）
 *  5. 多模态与规则引擎（normalizeMultimodal / analyzeVision / listRules / getRulePreset / executeRules / validateRules）
 */
import { api } from './client';

// ============================================================================
// 类型定义（与后端 app/schemas/intelligence.py 对齐）
// ============================================================================

export type PrimaryMode = 'chat' | 'reasoning' | 'agent' | 'hybrid' | 'auto';

export interface SessionResponse {
  id: string;
  user_id: string;
  project_id?: string | null;
  title: string;
  status: string;
  primary_mode: PrimaryMode;
  context?: Record<string, unknown> | null;
  last_message_at?: string | null;
  message_count: number;
  created_at?: string;
  updated_at?: string;
}

export interface SessionListResponse {
  items: SessionResponse[];
  total: number;
}

export interface SessionCreatePayload {
  title?: string;
  project_id?: string;
  primary_mode?: PrimaryMode;
}

export interface SessionArchivePayload {
  status: 'archived' | 'deleted';
}

export interface ChatRequest {
  message: string;
  project_id?: string;
  force_mode?: PrimaryMode;
}

export interface ChatResponse {
  answer: string;
  mode: string;
  [key: string]: unknown;
}

export interface ContextMemoryItem {
  id: string;
  type: string;
  content: unknown;
  importance: number;
  created_at?: string | null;
}

export interface ContextResponse {
  session_id: string;
  memories: ContextMemoryItem[];
  context_prompt: string;
}

export interface TraceStep {
  id: string;
  step_type: string;
  agent_name?: string | null;
  phase?: string | null;
  round_num?: number | null;
  decision_basis?: string | null;
  cost_usd?: number | null;
  duration_sec?: number | null;
  status: string;
  created_at?: string | null;
}

export interface TraceResponse {
  session_id: string;
  total_steps: number;
  traces: TraceStep[];
}

export interface TraceTreeResponse {
  roots: Array<Record<string, unknown>>;
  total_steps: number;
  total_cost: number;
}

export interface CostBreakdownResponse {
  total_cost: number;
  total_tokens: number;
  by_agent: Record<string, number>;
  by_phase: Record<string, number>;
  by_step_type: Record<string, number>;
}

export interface DecisionChainResponse {
  decisions: Array<Record<string, unknown>>;
}

export interface StreamCallbacks {
  onChunk?: (chunk: string) => void;
  onDone?: (fullText: string) => void;
  onError?: (err: Error) => void;
  signal?: AbortSignal;
}

export interface EvidenceCollectPayload {
  project_id?: string;
  entity_id?: string;
  trigger_event?: string;
  extra_evidence?: Record<string, unknown>;
}

export interface EvidenceResponse {
  text: string;
  sources: Array<Record<string, unknown>>;
  total_items: number;
  project_id?: string | null;
  entity_id?: string | null;
  trigger_event?: string | null;
}

export interface AnalysisInterpretPayload {
  message: string;
  analysis_data?: Record<string, unknown>;
  project_id?: string;
  intent?: string;
}

export interface DatasetInterpretPayload {
  message: string;
  project_id?: string;
}

export interface AnalysisInterpretResponse {
  interpretation?: string;
  suggestions?: string[];
  [key: string]: unknown;
}

export interface MultimodalNormalizePayload {
  text?: string;
  image_paths?: string[];
  image_urls?: string[];
  image_base64?: string[];
  file_paths?: string[];
  structured_data?: Record<string, unknown>;
}

export interface MultimodalNormalizeResponse {
  items: Array<Record<string, unknown>>;
  primary_text: string;
  has_image: boolean;
  modalities: string[];
  textualized: string;
}

export interface VisionAnalyzePayload {
  image_data_uri: string;
  analysis_type?: 'pathology' | 'protein_structure' | 'molecule_structure' | 'chart';
  prompt?: string;
  focus?: string;
}

export interface VisionAnalyzeResponse {
  [key: string]: unknown;
}

export interface RuleResponseItem {
  id: string;
  name: string;
  when: Record<string, unknown>;
  then: Array<Record<string, unknown>>;
  priority: number;
  enabled: boolean;
  description?: string;
  tags?: string[];
}

export interface RuleSetResponse {
  name: string;
  version: string;
  description?: string;
  rules: RuleResponseItem[];
}

export interface RuleListResponse {
  presets: string[];
  rulesets: RuleSetResponse[];
  total_rules: number;
}

export interface RuleExecutePayload {
  preset?: string;
  yaml_content?: string;
  context: Record<string, unknown>;
  tags?: string[];
}

export interface RuleExecuteResponse {
  ruleset_name: string;
  total_rules: number;
  matched_rules: number;
  executed_actions: number;
  results: Array<Record<string, unknown>>;
  context_changes: Record<string, unknown>;
  duration_sec: number;
}

export interface RuleValidatePayload {
  yaml_content: string;
}

export interface RuleValidateResponse {
  valid: boolean;
  errors: string[];
  rules_count: number;
  ruleset_name?: string | null;
}

// ============================================================================
// 内部工具
// ============================================================================

/** 解析 axios 响应已解包的 data 字段（响应拦截器自动拆信封） */
const unwrap = <T,>(resp: { data: unknown }): T => resp.data as T;

/** 构建 fetch URL（复用 client.ts 的 baseURL 规则） */
const API_BASE =
  (typeof process !== 'undefined' && process.env?.NEXT_PUBLIC_API_BASE) ||
  'http://localhost:8000/api/v1';

const buildUrl = (path: string): string => {
  const base = API_BASE.endsWith('/') ? API_BASE.slice(0, -1) : API_BASE;
  const cleanPath = path.startsWith('/') ? path : `/${path}`;
  return `${base}${cleanPath}`;
};

/** 从 localStorage 读取 JWT（与 client.ts 保持一致） */
const readAuthToken = (): string | null => {
  if (typeof window === 'undefined') return null;
  return window.localStorage.getItem('ai_drug_token');
};

// ============================================================================
// 1. 会话管理
// ============================================================================

export const createSession = (payload: SessionCreatePayload = {}): Promise<SessionResponse> =>
  api.post('/intelligence/sessions', payload).then(unwrap<SessionResponse>);

export const listSessions = (params: {
  project_id?: string;
  limit?: number;
} = {}): Promise<SessionListResponse> =>
  api.get('/intelligence/sessions', { params }).then(unwrap<SessionListResponse>);

export const getSession = (sessionId: string): Promise<SessionResponse> =>
  api.get(`/intelligence/sessions/${sessionId}`).then(unwrap<SessionResponse>);

export const archiveSession = (
  sessionId: string,
  payload: SessionArchivePayload = { status: 'archived' }
): Promise<SessionResponse> =>
  api.patch(`/intelligence/sessions/${sessionId}`, payload).then(unwrap<SessionResponse>);

// ============================================================================
// 2. 统一对话（非流式 + 流式）
// ============================================================================

/** 非流式 POST /intelligence/sessions/{sessionId}/chat */
export const sendChat = (
  sessionId: string,
  message: string,
  options: { projectId?: string; forceMode?: PrimaryMode } = {}
): Promise<ChatResponse> => {
  const body: ChatRequest = { message };
  if (options.projectId) body.project_id = options.projectId;
  if (options.forceMode) body.force_mode = options.forceMode;
  return api
    .post(`/intelligence/sessions/${sessionId}/chat`, body)
    .then(unwrap<ChatResponse>);
};

/** 强制切换主模式 */
export const forceMode = (sessionId: string, mode: PrimaryMode): Promise<{ primary_mode: string }> =>
  api
    .post(`/intelligence/sessions/${sessionId}/force-mode`, { mode })
    .then(unwrap<{ primary_mode: string }>);

/**
 * 流式对话（SSE）
 *
 * 由于 EventSource 仅支持 GET，这里使用 fetch + ReadableStream 解析 `data: xxx\n\n` 帧。
 * 后端会输出 `data: [DONE]\n\n` 作为结束帧，`data: [ERROR] xxx\n\n` 作为异常帧。
 */
export const streamChat = async (
  sessionId: string,
  message: string,
  options: {
    projectId?: string;
    forceMode?: PrimaryMode;
    onChunk?: (chunk: string) => void;
    onDone?: (fullText: string) => void;
    onError?: (err: Error) => void;
    signal?: AbortSignal;
  } = {}
): Promise<string> => {
  const url = buildUrl(`/intelligence/sessions/${sessionId}/stream`);

  const body: ChatRequest = { message };
  if (options.projectId) body.project_id = options.projectId;
  if (options.forceMode) body.force_mode = options.forceMode;

  const headers: Record<string, string> = {
    'Content-Type': 'application/json',
    Accept: 'text/event-stream',
  };
  const token = readAuthToken();
  if (token) headers['Authorization'] = `Bearer ${token}`;

  let response: Response;
  try {
    response = await fetch(url, {
      method: 'POST',
      headers,
      body: JSON.stringify(body),
      signal: options.signal,
      cache: 'no-store',
    });
  } catch (err) {
    const error = err instanceof Error ? err : new Error(String(err));
    options.onError?.(error);
    throw error;
  }

  if (!response.ok || !response.body) {
    const text = await response.text().catch(() => '');
    const error = new Error(
      `SSE 请求失败：HTTP ${response.status} ${response.statusText} ${text}`.trim()
    );
    options.onError?.(error);
    throw error;
  }

  const reader = response.body.getReader();
  const decoder = new TextDecoder('utf-8');
  let buffer = '';
  let fullText = '';

  try {
    while (true) {
      const { done, value } = await reader.read();
      if (done) break;

      buffer += decoder.decode(value, { stream: true });

      let sepIdx: number;
      while ((sepIdx = buffer.indexOf('\n\n')) !== -1) {
        const rawEvent = buffer.slice(0, sepIdx);
        buffer = buffer.slice(sepIdx + 2);

        const lines = rawEvent.split('\n');
        for (const line of lines) {
          const trimmed = line.trim();
          if (!trimmed.startsWith('data:')) continue;
          const data = trimmed.slice(5).trim();

          if (data === '[DONE]') {
            options.onDone?.(fullText);
            return fullText;
          }
          if (data.startsWith('[ERROR]')) {
            const errMsg = data.slice('[ERROR]'.length).trim() || '未知流式错误';
            const error = new Error(errMsg);
            options.onError?.(error);
            throw error;
          }

          fullText += data;
          options.onChunk?.(data);
        }
      }
    }

    if (buffer.trim().length > 0) {
      const lines = buffer.split('\n');
      for (const line of lines) {
        const trimmed = line.trim();
        if (!trimmed.startsWith('data:')) continue;
        const data = trimmed.slice(5).trim();
        if (data === '[DONE]') {
          options.onDone?.(fullText);
          return fullText;
        }
        if (data.startsWith('[ERROR]')) {
          const errMsg = data.slice('[ERROR]'.length).trim() || '未知流式错误';
          const error = new Error(errMsg);
          options.onError?.(error);
          throw error;
        }
        fullText += data;
        options.onChunk?.(data);
      }
    }

    options.onDone?.(fullText);
    return fullText;
  } catch (err) {
    if (err instanceof Error && err.name === 'AbortError') {
      throw err;
    }
    const error = err instanceof Error ? err : new Error(String(err));
    options.onError?.(error);
    throw error;
  } finally {
    try {
      reader.releaseLock?.();
    } catch {
      /* noop */
    }
  }
};

// ============================================================================
// 3. 上下文与追溯
// ============================================================================

export const getContext = (sessionId: string, limit = 50): Promise<ContextResponse> =>
  api
    .get(`/intelligence/sessions/${sessionId}/context`, { params: { limit } })
    .then(unwrap<ContextResponse>);

export const getTrace = (sessionId: string, limit = 200): Promise<TraceResponse> =>
  api
    .get(`/intelligence/sessions/${sessionId}/trace`, { params: { limit } })
    .then(unwrap<TraceResponse>);

export const getTraceTree = (runId: string): Promise<TraceTreeResponse> =>
  api.get(`/intelligence/runs/${runId}/trace-tree`).then(unwrap<TraceTreeResponse>);

export const getCostBreakdown = (runId: string): Promise<CostBreakdownResponse> =>
  api.get(`/intelligence/runs/${runId}/cost`).then(unwrap<CostBreakdownResponse>);

export const getDecisionChain = (runId: string): Promise<DecisionChainResponse> =>
  api.get(`/intelligence/runs/${runId}/decisions`).then(unwrap<DecisionChainResponse>);

// ============================================================================
// 4. 证据收集与分析
// ============================================================================

export const collectEvidence = (payload: EvidenceCollectPayload): Promise<EvidenceResponse> =>
  api.post('/intelligence/evidence/collect', payload).then(unwrap<EvidenceResponse>);

export const collectEntityContext = (payload: EvidenceCollectPayload): Promise<EvidenceResponse> =>
  api.post('/intelligence/evidence/collect-entity', payload).then(unwrap<EvidenceResponse>);

export const interpretAnalysis = (payload: AnalysisInterpretPayload): Promise<AnalysisInterpretResponse> =>
  api
    .post('/intelligence/analysis/interpret', payload)
    .then(unwrap<AnalysisInterpretResponse>);

export const interpretDataset = (
  datasetId: string,
  payload: DatasetInterpretPayload
): Promise<AnalysisInterpretResponse> =>
  api
    .post(`/intelligence/analysis/datasets/${datasetId}/interpret`, payload)
    .then(unwrap<AnalysisInterpretResponse>);

// ============================================================================
// 5. 多模态与规则引擎
// ============================================================================

export const normalizeMultimodal = (
  payload: MultimodalNormalizePayload
): Promise<MultimodalNormalizeResponse> =>
  api
    .post('/intelligence/multimodal/normalize', payload)
    .then(unwrap<MultimodalNormalizeResponse>);

export const analyzeVision = (payload: VisionAnalyzePayload): Promise<VisionAnalyzeResponse> =>
  api.post('/intelligence/vision/analyze', payload).then(unwrap<VisionAnalyzeResponse>);

export const listRules = (): Promise<RuleListResponse> =>
  api.get('/intelligence/rules').then(unwrap<RuleListResponse>);

export const getRulePreset = (preset: string): Promise<RuleSetResponse> =>
  api.get(`/intelligence/rules/${preset}`).then(unwrap<RuleSetResponse>);

export const executeRules = (payload: RuleExecutePayload): Promise<RuleExecuteResponse> =>
  api.post('/intelligence/rules/execute', payload).then(unwrap<RuleExecuteResponse>);

export const validateRules = (payload: RuleValidatePayload): Promise<RuleValidateResponse> =>
  api.post('/intelligence/rules/validate', payload).then(unwrap<RuleValidateResponse>);
