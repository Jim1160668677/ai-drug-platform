/**
 * AgentSession 状态机 — 前端会话生命周期 + WS 连接管理
 *
 * 设计来源：2026-07-18-agent-functional-design.md §2.4.2
 *
 * 会话活跃状态：
 *   idle ──首条消息──▶ active ──5min 无活动──▶ paused ──30天──▶ archived
 *                         ▲                       │
 *                         └──────新消息────────────┘
 *
 * paused 状态下 WS 拒绝新连接（提示"会话已暂停，发送消息以唤醒"），但历史可查。
 *
 * WS 连接子状态（active 内部）：
 *   connecting ──▶ connected ──▶ disconnecting ──▶ disconnected
 *        └─────────────◀─────────────(reconnect)
 *
 * 事件来源：用户切换会话、WS 连接/断开/错误、5min 无活动定时器、用户发送消息
 */
import { setup, assign } from 'xstate';
import type { SessionStatus } from '@/types/agent';

// ========== 上下文 ==========
export interface AgentSessionContext {
  /** 当前会话 ID */
  sessionId: string | null;
  /** 会话标题 */
  title: string | null;
  /** 后端同步的会话状态 */
  sessionStatus: SessionStatus;
  /** WS 连接 URL */
  wsUrl: string | null;
  /** 最近一次活动时间戳（ISO） */
  lastActivityAt: string | null;
  /** 重连次数 */
  reconnectAttempts: number;
  /** 最大重连次数 */
  maxReconnectAttempts: number;
  /** 连接错误 */
  error: string | null;
}

const initialContext: AgentSessionContext = {
  sessionId: null,
  title: null,
  sessionStatus: 'active',
  wsUrl: null,
  lastActivityAt: null,
  reconnectAttempts: 0,
  maxReconnectAttempts: 5,
  error: null,
};

// ========== 事件 ==========
export type AgentSessionEvent =
  // 用户选择/切换会话
  | { type: 'SELECT_SESSION'; sessionId: string; title: string; status: SessionStatus }
  // WS 连接开始
  | { type: 'CONNECT' }
  // WS 连接成功
  | { type: 'CONNECTED' }
  // WS 连接失败
  | { type: 'CONNECT_FAILED'; error: string }
  // WS 断开
  | { type: 'DISCONNECTED' }
  // 用户主动断开（切换会话/登出）
  | { type: 'DISCONNECT' }
  // 重连
  | { type: 'RECONNECT' }
  // 用户发送消息（刷新活跃度）
  | { type: 'MESSAGE_SENT' }
  // 收到消息（刷新活跃度）
  | { type: 'MESSAGE_RECEIVED' }
  // 5min 无活动定时器触发
  | { type: 'INACTIVITY_TIMEOUT' }
  // 用户唤醒暂停的会话
  | { type: 'RESUME' }
  // 会话被归档（30天）
  | { type: 'ARCHIVE' }
  // 清空会话（登出/关闭）
  | { type: 'CLEAR' };

// ========== 状态机 ==========
export const agentSessionMachine = setup({
  types: {
    context: {} as AgentSessionContext,
    events: {} as AgentSessionEvent,
  },
  actions: {
    setSessionMeta: assign(({ event }) => {
      if (event.type !== 'SELECT_SESSION') return {};
      return {
        sessionId: event.sessionId,
        title: event.title,
        sessionStatus: event.status,
        reconnectAttempts: 0,
        error: null,
      } as Partial<AgentSessionContext>;
    }),
    setWsConnecting: assign(() => ({
      error: null,
    }) as Partial<AgentSessionContext>),
    setConnected: assign(() => ({
      reconnectAttempts: 0,
      lastActivityAt: new Date().toISOString(),
      sessionStatus: 'active' as SessionStatus,
      error: null,
    }) as Partial<AgentSessionContext>),
    setConnectError: assign(({ event, context }) => {
      if (event.type !== 'CONNECT_FAILED') return {};
      return {
        error: event.error,
        reconnectAttempts: context.reconnectAttempts + 1,
      } as Partial<AgentSessionContext>;
    }),
    incrementReconnect: assign(({ context }) => ({
      reconnectAttempts: context.reconnectAttempts + 1,
    }) as Partial<AgentSessionContext>),
    touchActivity: assign(() => ({
      lastActivityAt: new Date().toISOString(),
    }) as Partial<AgentSessionContext>),
    setPaused: assign(() => ({
      sessionStatus: 'paused' as SessionStatus,
    }) as Partial<AgentSessionContext>),
    setArchived: assign(() => ({
      sessionStatus: 'archived' as SessionStatus,
    }) as Partial<AgentSessionContext>),
    clearContext: assign(() => ({ ...initialContext })),
  },
  guards: {
    canReconnect: ({ context }) =>
      context.reconnectAttempts < context.maxReconnectAttempts,
  },
}).createMachine({
  id: 'agentSession',
  initial: 'idle',
  context: initialContext,
  states: {
    // 空闲：无会话或未连接
    idle: {
      on: {
        SELECT_SESSION: { target: 'active.connecting', actions: 'setSessionMeta' },
      },
    },

    // 活跃：会话已选择，管理 WS 连接子状态
    active: {
      initial: 'connecting',
      on: {
        INACTIVITY_TIMEOUT: { target: 'paused', actions: 'setPaused' },
        ARCHIVE: { target: 'archived', actions: 'setArchived' },
        CLEAR: { target: 'idle', actions: 'clearContext' },
      },
      states: {
        // WS 连接中
        connecting: {
          on: {
            CONNECTED: { target: 'connected', actions: 'setConnected' },
            CONNECT_FAILED: { target: '#agentSession.error', actions: 'setConnectError' },
            DISCONNECT: { target: '#agentSession.idle' },
          },
        },
        // WS 已连接
        connected: {
          on: {
            MESSAGE_SENT: { actions: 'touchActivity', internal: true },
            MESSAGE_RECEIVED: { actions: 'touchActivity', internal: true },
            DISCONNECTED: { target: 'reconnecting' },
            DISCONNECT: { target: 'disconnecting' },
          },
        },
        // 断开中（用户主动）
        disconnecting: {
          on: {
            DISCONNECTED: { target: '#agentSession.idle' },
          },
        },
        // 重连中（异常断开）
        reconnecting: {
          always: {
            target: 'connecting',
            guard: 'canReconnect',
            actions: 'incrementReconnect',
          },
        },
      },
    },

    // 错误：连接失败
    error: {
      on: {
        RECONNECT: { target: 'active.connecting', actions: 'setWsConnecting' },
        DISCONNECT: { target: 'idle', actions: 'clearContext' },
      },
    },

    // 暂停：5min 无活动，WS 拒绝新连接但历史可查
    paused: {
      on: {
        RESUME: { target: 'active.connecting', actions: 'touchActivity' },
        ARCHIVE: { target: 'archived', actions: 'setArchived' },
        CLEAR: { target: 'idle', actions: 'clearContext' },
      },
    },

    // 归档：30天，只读
    archived: {
      type: 'final',
    },
  },
});

// ========== 辅助函数 ==========
/** XState v5 嵌套状态值类型：顶层状态为 string，子状态为对象 */
type StateValue = string | Record<string, unknown>;

/** 将 stateValue 标准化为可比较的字符串（如 "active.connected"） */
function normalizeStateValue(sv: StateValue): string {
  if (typeof sv === 'string') return sv;
  // 形如 { active: 'connected' } → 'active.connected'
  const keys = Object.keys(sv);
  if (keys.length === 0) return '';
  const parent = keys[0];
  const child = sv[parent];
  if (typeof child === 'string') return `${parent}.${child}`;
  if (child && typeof child === 'object') return `${parent}.${normalizeStateValue(child)}`;
  return parent;
}

/** 判断会话是否可发送消息（active 且 WS 已连接） */
export function canSendMessage(stateValue: StateValue): boolean {
  return normalizeStateValue(stateValue) === 'active.connected';
}

/** 判断会话是否处于只读状态（paused/archived） */
export function isReadOnlySession(stateValue: StateValue): boolean {
  const s = normalizeStateValue(stateValue);
  return s === 'paused' || s === 'archived';
}

/** 判断 WS 是否已连接 */
export function isWSConnected(stateValue: StateValue): boolean {
  return normalizeStateValue(stateValue) === 'active.connected';
}

/** 判断是否正在连接/重连中 */
export function isConnecting(stateValue: StateValue): boolean {
  const s = normalizeStateValue(stateValue);
  return s === 'active.connecting' || s === 'active.reconnecting' || s === 'error';
}
