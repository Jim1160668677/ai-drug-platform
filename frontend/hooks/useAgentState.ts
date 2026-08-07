'use client';

import { useCallback, useEffect, useRef, useState } from 'react';
import { useMachine } from '@xstate/react';
import { useAppStore } from '@/lib/store';
import {
  AgentWebSocket,
  createSession as apiCreateSession,
  listSessions as apiListSessions,
  sendChat as apiSendChat,
  cancelTask as apiCancelTask,
} from '@/lib/api';
import { agentTaskMachine, isRunningState, canSubmitTask } from '@/lib/machines/agent-task-machine';
import type {
  AgentSession,
  AgentMessage,
  WSEvent,
  ConfirmationRequiredPayload,
  TaskStatus,
  Plan,
} from '@/types/agent';

/**
 * Agent 工作台状态整合 Hook
 *
 * 整合 store + WS + REST API + XState 状态机，对外暴露简单接口。
 * 设计来源：2026-07-18-agent-functional-design.md §4
 *
 * XState 集成（v2 增强）：
 * - agentTaskMachine 管理任务生命周期（pending → planning → running → completed/failed/cancelled）
 * - WS 事件同步转发到状态机，UI 可从 taskStatus 派生更精细的展示
 * - isSending 从状态机派生（isRunningState），替代原先的布尔标志
 */
export function useAgentState() {
  const store = useAppStore();
  const [wsClient, setWsClient] = useState<AgentWebSocket | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [wsStatus, setWsStatus] = useState<
    'connected' | 'connecting' | 'reconnecting' | 'disconnected'
  >('disconnected');
  const clientRef = useRef<AgentWebSocket | null>(null);

  // ========== XState 任务状态机 ==========
  const [taskState, taskSend] = useMachine(agentTaskMachine);

  // ========== 加载会话列表 ==========
  const loadSessions = useCallback(async () => {
    try {
      const data = await apiListSessions({ page: 1, page_size: 50 });
      const sessions = (data?.data ?? data?.items) ?? [];
      store.setAgentSessions(sessions);
      // 若无当前会话且列表非空，默认选第一个
      if (!store.currentSessionId && sessions.length > 0) {
        store.setCurrentSession(sessions[0].id);
      }
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : '加载会话列表失败';
      setError(msg);
    }
  }, [store]);

  useEffect(() => {
    loadSessions();
  }, [loadSessions]);

  // ========== 自动创建首个会话（修复进入页面即"已断开"的体验） ==========
  // 会话列表为空时自动创建一个，使 WS 能立即建立连接
  // 修复：依赖项改为 [store.agentSessions.length]，避免布尔表达式依赖导致的
  // 闭包陈旧问题；并用 ref 防止重复创建
  const hasTriedAutoCreate = useRef(false);
  useEffect(() => {
    if (
      store.agentSessions.length === 0 &&
      !store.currentSessionId &&
      !store.agentLoading &&
      !hasTriedAutoCreate.current
    ) {
      hasTriedAutoCreate.current = true;
      createNewSession('默认会话').then((session) => {
        // 创建失败时重置 flag，允许后续重试
        if (!session) {
          hasTriedAutoCreate.current = false;
        }
      });
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [store.agentSessions.length]);

  // ========== 切换会话时建立 WS ==========
  useEffect(() => {
    // 清理上一次连接
    if (clientRef.current) {
      clientRef.current.disconnect();
      clientRef.current = null;
      setWsClient(null);
    }

    if (!store.currentSessionId) {
      setWsStatus('disconnected');
      return;
    }

    const token =
      typeof window !== 'undefined'
        ? localStorage.getItem('ai_drug_token') || ''
        : '';
    if (!token) {
      setError('未登录');
      setWsStatus('disconnected');
      return;
    }

    setWsStatus('connecting');
    const client = new AgentWebSocket(
      { sessionId: store.currentSessionId, token },
      {
        onEvent: handleWSEvent,
        onConnected: () => setWsStatus('connected'),
        onDisconnected: () => {
          // 重连由 AgentWebSocket 内部处理；切到 reconnecting 让 UI 提示
          setWsStatus('reconnecting');
        },
        onError: () => {
          setError('WebSocket 连接异常');
        },
      }
    );
    client.connect();
    clientRef.current = client;
    setWsClient(client);

    return () => {
      client.disconnect();
      clientRef.current = null;
      setWsClient(null);
      setWsStatus('disconnected');
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [store.currentSessionId]);

  // ========== WS 事件处理（同步转发到 XState 状态机） ==========
  const handleWSEvent = useCallback(
    (event: WSEvent) => {
      const ts = new Date().toISOString();

      switch (event.type) {
        case 'task_started':
          // 状态机：pending → planning
          taskSend({ type: 'TASK_STARTED' });
          break;

        case 'token': {
          // 流式 token：累积到 streaming 消息中，让用户看到 LLM 实时输出
          const payload = event.payload as { token?: string; step?: number };
          if (payload.token) {
            store.appendStreamingToken(payload.token, payload.step);
          }
          break;
        }

        case 'plan': {
          // 状态机：planning → running
          const payload = event.payload as { steps?: unknown[]; parallel_layers?: string[][] };
          if (payload && (payload.steps || payload.parallel_layers)) {
            taskSend({
              type: 'PLAN_READY',
              plan: {
                steps: (payload.steps ?? []) as Plan['steps'],
                parallel_layers: payload.parallel_layers ?? [],
              },
            });
          }
          break;
        }

        case 'thought': {
          const payload = event.payload as { thought?: string; step?: number };
          // 清理流式 streaming 消息（被结构化 thought 取代）
          store.clearStreamingMessage();
          // 状态机：推进步数
          if (payload.step) {
            taskSend({ type: 'STEP_START', step: payload.step });
          }
          // thought 作为 assistant 消息追加
          store.appendMessage({
            id: `msg-${Date.now()}-thought`,
            role: 'assistant',
            content: payload.thought ?? '',
            thought: payload.thought,
            step: payload.step,
            timestamp: ts,
          });
          break;
        }

        case 'tool_call': {
          const payload = event.payload as {
            step: number;
            tool: string;
            args: Record<string, unknown>;
            thought?: string;
          };
          // 清理流式 streaming 消息（ReAct 已进入工具调用阶段）
          store.clearStreamingMessage();
          store.appendToolCall(event.task_id, payload);
          break;
        }

        case 'tool_result': {
          const payload = event.payload as {
            step: number;
            tool: string;
            success: boolean;
            data?: unknown;
            error?: string;
            duration_ms?: number;
          };
          store.appendToolResult(event.task_id, payload);
          break;
        }

        case 'confirmation_required': {
          const payload = event.payload as ConfirmationRequiredPayload;
          // 状态机：running → awaiting_confirmation
          taskSend({
            type: 'CONFIRMATION_REQUIRED',
            tool: payload.tool,
            args: payload.args,
          });
          store.setPendingConfirmation({
            task_id: payload.task_id || event.task_id,
            tool: payload.tool,
            args: payload.args,
          });
          break;
        }

        case 'final_response': {
          const payload = event.payload as {
            answer: string;
            references?: Array<{ title?: string; source?: string }>;
          };
          // 清理流式 streaming 消息（最终答案到达，streaming 已无意义）
          store.clearStreamingMessage();
          // 状态机：running → completed
          taskSend({ type: 'FINAL_RESPONSE', answer: payload.answer });
          store.appendMessage({
            id: `msg-${Date.now()}-final`,
            role: 'assistant',
            content: payload.answer,
            timestamp: ts,
            meta: {
              task_id: event.task_id,
              references: payload.references as unknown as undefined,
            },
          });
          store.setAgentLoading(false);
          break;
        }

        case 'task_completed': {
          const payload = event.payload as {
            answer?: string;
            token_usage?: { prompt: number; completion: number; total: number };
            cost_usd?: number;
            duration_sec?: number;
            status?: string;
          };
          // 状态机：running → completed（携带元数据）
          taskSend({
            type: 'TASK_COMPLETED',
            tokenUsage: payload.token_usage,
            costUsd: payload.cost_usd,
            durationSec: payload.duration_sec,
          });
          // 若 final_response 未推送答案，task_completed 兜底
          if (payload.answer) {
            store.appendMessage({
              id: `msg-${Date.now()}-completed`,
              role: 'assistant',
              content: payload.answer,
              timestamp: ts,
              meta: {
                task_id: event.task_id,
                token_usage: payload.token_usage,
                cost_usd: payload.cost_usd,
                duration_sec: payload.duration_sec,
                status: payload.status as AgentMessage['meta'] extends never ? never : any,
              },
            });
          }
          store.setAgentLoading(false);
          break;
        }

        case 'task_cancelled':
          // 状态机：running → cancelled
          taskSend({ type: 'TASK_CANCELLED' });
          store.setAgentLoading(false);
          break;

        case 'error': {
          const payload = event.payload as { error: string; error_code?: string };
          // 清理流式 streaming 消息（任务失败，streaming 无意义）
          store.clearStreamingMessage();
          // 状态机：→ failed
          taskSend({ type: 'TASK_FAILED', error: payload.error, errorCode: payload.error_code });
          setError(payload.error);
          store.setAgentLoading(false);
          store.appendMessage({
            id: `msg-${Date.now()}-error`,
            role: 'system',
            content: `⚠️ ${payload.error}`,
            timestamp: ts,
          });
          break;
        }

        case 'force_close':
          setError('连接超时，请重新进入会话');
          break;

        default:
          // ping / pong / connected / progress_snapshot / not_found / unsubscribed 忽略
          break;
      }
    },
    [store, taskSend]
  );

  // ========== 发送对话 ==========
  const send = useCallback(
    async (message: string) => {
      if (!message.trim() || !store.currentSessionId) {
        if (!store.currentSessionId) {
          setError('请先选择或创建会话');
        }
        return;
      }

      // 状态机守卫：运行中不允许提交新任务
      if (!canSubmitTask(taskState.value as string)) {
        setError('当前任务仍在执行，请等待完成或取消后再发送');
        return;
      }

      setError(null);
      // 追加 user 消息
      store.appendMessage({
        id: `msg-${Date.now()}-user`,
        role: 'user',
        content: message,
        timestamp: new Date().toISOString(),
      });
      store.setAgentLoading(true);

      try {
        const resp = await apiSendChat({
          session_id: store.currentSessionId,
          message,
          project_id: store.currentProject?.id,
          tier: 'deep_insight',
        });
        store.setCurrentTaskId(resp.task_id);
        // 状态机：idle → pending（提交新任务）
        taskSend({
          type: 'SUBMIT',
          taskId: resp.task_id,
          sessionId: store.currentSessionId,
          query: message,
        });
        // 通过 WS 订阅该任务
        wsClient?.subscribe(resp.task_id);
      } catch (err: unknown) {
        const msg = err instanceof Error ? err.message : '发送失败';
        setError(msg);
        store.setAgentLoading(false);
        // 状态机：提交失败回 idle（不进入 pending）
        taskSend({ type: 'RESET' });
      }
    },
    [store, wsClient, taskState, taskSend]
  );

  // ========== 创建新会话 ==========
  const createNewSession = useCallback(
    async (title?: string) => {
      try {
        const session = await apiCreateSession({
          title: title || '新会话',
          project_id: store.currentProject?.id,
        });
        const newSession: AgentSession = {
          ...(session as AgentSession),
          id: (session as AgentSession).id,
        };
        store.setAgentSessions([newSession, ...store.agentSessions]);
        store.setCurrentSession(newSession.id);
        return newSession;
      } catch (err: unknown) {
        const msg = err instanceof Error ? err.message : '创建会话失败';
        setError(msg);
        return null;
      }
    },
    [store]
  );

  // ========== 取消任务 ==========
  const cancelTask = useCallback(
    async (taskId: string) => {
      try {
        await apiCancelTask(taskId);
        // 状态机：running → cancelled（乐观更新，后端会回推 TASK_CANCELLED 确认）
        taskSend({ type: 'CANCEL' });
        store.setAgentLoading(false);
      } catch (err: unknown) {
        const msg = err instanceof Error ? err.message : '取消失败';
        setError(msg);
      }
    },
    [store, taskSend]
  );

  // ========== 确认副作用工具 ==========
  const confirmTool = useCallback(
    (taskId: string, approved: boolean) => {
      wsClient?.confirm(taskId, approved);
      // 状态机：awaiting_confirmation → running
      taskSend(approved ? { type: 'CONFIRMED' } : { type: 'REJECTED' });
      store.setPendingConfirmation(null);
    },
    [wsClient, store, taskSend]
  );

  // ========== 选择会话 ==========
  const selectSession = useCallback(
    (id: string) => {
      store.setCurrentSession(id);
      // 切换会话时重置任务状态机
      taskSend({ type: 'RESET' });
    },
    [store, taskSend]
  );

  // ========== 从状态机派生 UI 状态 ==========
  const taskStatusValue = taskState.value as string;
  const isSending = isRunningState(taskStatusValue);
  // 映射状态机值到 TaskStatus 类型（供 UI 展示任务阶段）
  const taskStatus: TaskStatus | undefined = isRunningState(taskStatusValue)
    ? (taskStatusValue as TaskStatus)
    : taskStatusValue === 'completed'
      ? 'completed'
      : taskStatusValue === 'failed'
        ? 'failed'
        : taskStatusValue === 'cancelled'
          ? 'cancelled'
          : undefined;

  // 任务进度（供 ChatInput 进度条使用）
  const taskProgress = {
    currentStep: taskState.context.currentStep,
    maxSteps: taskState.context.maxSteps,
    durationSec: taskState.context.durationSec || undefined,
  };

  return {
    // 状态
    sessions: store.agentSessions,
    currentSessionId: store.currentSessionId,
    currentTaskId: store.currentTaskId,
    messages: store.messages,
    isSending,
    pendingConfirmation: store.pendingConfirmation,
    latestToolResult: store.latestToolResult,
    error,
    // XState 派生（v2 新增）
    taskStatus,
    taskState: taskStatusValue,
    canSubmit: canSubmitTask(taskStatusValue),
    taskProgress,
    // WebSocket 连接状态（v2 新增）
    wsStatus,
    // 操作
    selectSession,
    createNewSession,
    send,
    cancelTask,
    confirmTool,
    loadSessions,
    clearError: () => setError(null),
  };
}
