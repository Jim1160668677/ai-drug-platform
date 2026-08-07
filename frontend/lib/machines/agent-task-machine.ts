/**
 * AgentTask 状态机 — 前端任务生命周期管理
 *
 * 设计来源：2026-07-18-agent-functional-design.md §2.4.1
 *
 * 状态转移图：
 *   pending ──▶ planning ──▶ running ──▶ completed
 *      │           │            │
 *      │           │            ├──▶ failed     (max_steps / timeout / llm_error)
 *      │           │            └──▶ cancelled  (user /stop)
 *      │           └──▶ failed  (planner retry exhausted)
 *      └──▶ failed (rate_limited / guardrail_blocked)
 *
 * awaiting_confirmation 是 running 下的子状态（对应单步 ReAct 的 waiting_confirm），
 * 前端为 UI 展示便利提升为顶层状态。
 *
 * 事件来源：后端 WebSocket 事件（task_started/plan/thought/tool_call/tool_result/
 *           confirmation_required/final_response/task_completed/task_cancelled/error）
 */
import { setup, assign } from 'xstate';
import type { TaskStatus, TokenUsage, Plan } from '@/types/agent';

// ========== 上下文 ==========
export interface AgentTaskContext {
  /** 当前任务 ID */
  taskId: string | null;
  /** 当前会话 ID */
  sessionId: string | null;
  /** 用户原始提问 */
  query: string;
  /** 任务规划（planning 阶段产出） */
  plan: Plan | null;
  /** 当前执行步数 */
  currentStep: number;
  /** 最大步数（来自后端 settings.AGENT_MAX_STEPS，默认 15） */
  maxSteps: number;
  /** token 用量 */
  tokenUsage: TokenUsage | null;
  /** 花费（美元） */
  costUsd: number;
  /** 已耗时（秒） */
  durationSec: number;
  /** 错误信息（failed 状态） */
  error: string | null;
  /** 错误码 */
  errorCode: string | null;
  /** 待确认的工具调用（awaiting_confirmation 状态） */
  pendingConfirmation: {
    tool: string;
    args: Record<string, unknown>;
  } | null;
}

const initialContext: AgentTaskContext = {
  taskId: null,
  sessionId: null,
  query: '',
  plan: null,
  currentStep: 0,
  maxSteps: 15,
  tokenUsage: null,
  costUsd: 0,
  durationSec: 0,
  error: null,
  errorCode: null,
  pendingConfirmation: null,
};

// ========== 事件 ==========
export type AgentTaskEvent =
  // 外部触发：提交新任务
  | { type: 'SUBMIT'; taskId: string; sessionId: string; query: string; maxSteps?: number }
  // WS 事件：任务已开始（进入 planning）
  | { type: 'TASK_STARTED'; plan?: Plan }
  // WS 事件：规划就绪（进入 running）
  | { type: 'PLAN_READY'; plan: Plan }
  // WS 事件：规划失败
  | { type: 'PLAN_FAILED'; error: string }
  // WS 事件：开始执行某步
  | { type: 'STEP_START'; step: number }
  // WS 事件：需要确认副作用工具
  | { type: 'CONFIRMATION_REQUIRED'; tool: string; args: Record<string, unknown> }
  // 用户操作：确认/拒绝副作用工具
  | { type: 'CONFIRMED' }
  | { type: 'REJECTED' }
  // WS 事件：最终答案就绪
  | { type: 'FINAL_RESPONSE'; answer: string }
  // WS 事件：任务完成
  | { type: 'TASK_COMPLETED'; tokenUsage?: TokenUsage; costUsd?: number; durationSec?: number }
  // WS 事件：任务失败
  | { type: 'TASK_FAILED'; error: string; errorCode?: string }
  // WS 事件：任务取消
  | { type: 'TASK_CANCELLED' }
  // 用户操作：取消任务
  | { type: 'CANCEL' }
  // 用户操作：重置到 idle（开始新任务前）
  | { type: 'RESET' };

// ========== 状态机 ==========
export const agentTaskMachine = setup({
  types: {
    context: {} as AgentTaskContext,
    events: {} as AgentTaskEvent,
  },
  actions: {
    setTaskMeta: assign(({ event }) => {
      if (event.type !== 'SUBMIT') return {};
      return {
        taskId: event.taskId,
        sessionId: event.sessionId,
        query: event.query,
        maxSteps: event.maxSteps ?? 15,
      } as Partial<AgentTaskContext>;
    }),
    setPlan: assign(({ event }) => {
      if (event.type !== 'PLAN_READY' && event.type !== 'TASK_STARTED') return {};
      const plan = event.type === 'PLAN_READY' ? event.plan : event.plan ?? null;
      return { plan } as Partial<AgentTaskContext>;
    }),
    advanceStep: assign(({ event }) => {
      if (event.type !== 'STEP_START') return {};
      return { currentStep: event.step } as Partial<AgentTaskContext>;
    }),
    setConfirmation: assign(({ event }) => {
      if (event.type !== 'CONFIRMATION_REQUIRED') return {};
      return {
        pendingConfirmation: { tool: event.tool, args: event.args },
      } as Partial<AgentTaskContext>;
    }),
    clearConfirmation: assign(() => ({
      pendingConfirmation: null,
    }) as Partial<AgentTaskContext>),
    setCompleted: assign(({ event }) => {
      if (event.type !== 'TASK_COMPLETED') return {};
      return {
        tokenUsage: event.tokenUsage ?? null,
        costUsd: event.costUsd ?? 0,
        durationSec: event.durationSec ?? 0,
      } as Partial<AgentTaskContext>;
    }),
    setError: assign(({ event }) => {
      if (event.type !== 'TASK_FAILED' && event.type !== 'PLAN_FAILED') return {};
      return {
        error: event.error,
        errorCode: event.type === 'TASK_FAILED' ? event.errorCode ?? null : 'PLANNER_FAILED',
      } as Partial<AgentTaskContext>;
    }),
    resetContext: assign(() => ({ ...initialContext })),
  },
}).createMachine({
  id: 'agentTask',
  initial: 'idle',
  context: initialContext,
  states: {
    // 空闲：等待用户提交新任务
    idle: {
      on: {
        SUBMIT: { target: 'pending', actions: 'setTaskMeta' },
      },
    },

    // 已提交，等待后端 task_started（护栏/限流检查阶段）
    pending: {
      on: {
        TASK_STARTED: { target: 'planning', actions: 'setPlan' },
        TASK_FAILED: { target: 'failed', actions: 'setError' }, // rate_limited / guardrail_blocked
        CANCEL: { target: 'cancelled' },
      },
    },

    // 规划中：等待 plan 事件
    planning: {
      on: {
        PLAN_READY: { target: 'running', actions: 'setPlan' },
        PLAN_FAILED: { target: 'failed', actions: 'setError' }, // planner retry exhausted
        TASK_FAILED: { target: 'failed', actions: 'setError' },
        CANCEL: { target: 'cancelled' },
      },
    },

    // 执行中：ReAct 循环
    running: {
      on: {
        STEP_START: { target: 'running', actions: 'advanceStep', internal: true },
        CONFIRMATION_REQUIRED: { target: 'awaiting_confirmation', actions: 'setConfirmation' },
        FINAL_RESPONSE: { target: 'completed' },
        TASK_COMPLETED: { target: 'completed', actions: 'setCompleted' },
        TASK_FAILED: { target: 'failed', actions: 'setError' }, // max_steps / timeout / llm_error
        CANCEL: { target: 'cancelled' },
        TASK_CANCELLED: { target: 'cancelled' },
      },
    },

    // 等待用户确认副作用工具
    awaiting_confirmation: {
      on: {
        CONFIRMED: { target: 'running', actions: 'clearConfirmation' },
        REJECTED: { target: 'running', actions: 'clearConfirmation' }, // 拒绝后引擎跳过该步继续
        TASK_FAILED: { target: 'failed', actions: 'setError' },
        CANCEL: { target: 'cancelled' },
        TASK_CANCELLED: { target: 'cancelled' },
      },
    },

    // 终态：完成（保留 RESET 转移以便前端开始新任务；不设 type:final 避免 actor 停止）
    completed: {
      on: {
        RESET: { target: 'idle', actions: 'resetContext' },
      },
    },

    // 终态：失败
    failed: {
      on: {
        RESET: { target: 'idle', actions: 'resetContext' },
      },
    },

    // 终态：取消
    cancelled: {
      on: {
        RESET: { target: 'idle', actions: 'resetContext' },
      },
    },
  },
  on: {
    RESET: { target: '#agentTask.idle', actions: 'resetContext' },
  },
});

// ========== 辅助函数 ==========
/** 当前状态是否为终态 */
export function isTerminalStatus(status: TaskStatus): boolean {
  return status === 'completed' || status === 'failed' || status === 'cancelled';
}

/** 当前状态是否允许发送新消息（仅 idle/终态允许） */
export function canSubmitTask(stateValue: string): boolean {
  return stateValue === 'idle' || stateValue === 'completed' ||
         stateValue === 'failed' || stateValue === 'cancelled';
}

/** 当前状态是否显示"运行中"UI（loading 指示器） */
export function isRunningState(stateValue: string): boolean {
  return stateValue === 'pending' || stateValue === 'planning' ||
         stateValue === 'running' || stateValue === 'awaiting_confirmation';
}
