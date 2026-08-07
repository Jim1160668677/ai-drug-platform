/**
 * AgentTask 状态机单元测试
 *
 * 验证设计文档 §2.4.1 定义的状态转移：
 *   pending → planning → running → completed
 *   pending/planning/running → failed (rate_limited/guardrail/planner/timeout/max_steps)
 *   running → cancelled (user /stop)
 */
import { describe, it, expect } from 'vitest';
import { createActor } from 'xstate';
import {
  agentTaskMachine,
  isTerminalStatus,
  canSubmitTask,
  isRunningState,
  type AgentTaskEvent,
} from './agent-task-machine';

/** 创建 actor 并发送事件序列，返回最终状态值 */
function runTaskMachine(events: AgentTaskEvent[]): string {
  const actor = createActor(agentTaskMachine);
  actor.start();
  for (const evt of events) {
    actor.send(evt);
  }
  const snapshot = actor.getSnapshot();
  return snapshot.value as string;
}

describe('agentTaskMachine — 状态转移', () => {
  describe('正常流程', () => {
    it('idle → pending → planning → running → completed（完整成功路径）', () => {
      const state = runTaskMachine([
        { type: 'SUBMIT', taskId: 't1', sessionId: 's1', query: '查询 EGFR 靶点' },
        { type: 'TASK_STARTED' },
        { type: 'PLAN_READY', plan: { steps: [], parallel_layers: [] } },
        { type: 'STEP_START', step: 1 },
        { type: 'FINAL_RESPONSE', answer: 'EGFR 是...' },
      ]);
      expect(state).toBe('completed');
    });

    it('TASK_COMPLETED 也能进入 completed 并记录元数据', () => {
      const actor = createActor(agentTaskMachine);
      actor.start();
      actor.send({ type: 'SUBMIT', taskId: 't1', sessionId: 's1', query: '测试' });
      actor.send({ type: 'TASK_STARTED' });
      actor.send({ type: 'PLAN_READY', plan: { steps: [], parallel_layers: [] } });
      actor.send({
        type: 'TASK_COMPLETED',
        tokenUsage: { prompt: 100, completion: 50, total: 150 },
        costUsd: 0.002,
        durationSec: 3.5,
      });
      const snap = actor.getSnapshot();
      expect(snap.value).toBe('completed');
      expect(snap.context.tokenUsage?.total).toBe(150);
      expect(snap.context.costUsd).toBe(0.002);
      expect(snap.context.durationSec).toBe(3.5);
    });
  });

  describe('awaiting_confirmation 子状态', () => {
    it('running → awaiting_confirmation → running（确认后继续）', () => {
      const state = runTaskMachine([
        { type: 'SUBMIT', taskId: 't1', sessionId: 's1', query: '执行代码' },
        { type: 'TASK_STARTED' },
        { type: 'PLAN_READY', plan: { steps: [], parallel_layers: [] } },
        { type: 'CONFIRMATION_REQUIRED', tool: 'execute_code', args: { code: 'print(1)' } },
      ]);
      expect(state).toBe('awaiting_confirmation');
    });

    it('CONFIRMED 后回到 running', () => {
      const state = runTaskMachine([
        { type: 'SUBMIT', taskId: 't1', sessionId: 's1', query: '执行代码' },
        { type: 'TASK_STARTED' },
        { type: 'PLAN_READY', plan: { steps: [], parallel_layers: [] } },
        { type: 'CONFIRMATION_REQUIRED', tool: 'execute_code', args: { code: 'print(1)' } },
        { type: 'CONFIRMED' },
      ]);
      expect(state).toBe('running');
    });

    it('REJECTED 后也回到 running（引擎跳过该步继续）', () => {
      const state = runTaskMachine([
        { type: 'SUBMIT', taskId: 't1', sessionId: 's1', query: '执行代码' },
        { type: 'TASK_STARTED' },
        { type: 'PLAN_READY', plan: { steps: [], parallel_layers: [] } },
        { type: 'CONFIRMATION_REQUIRED', tool: 'execute_code', args: { code: 'print(1)' } },
        { type: 'REJECTED' },
        { type: 'FINAL_RESPONSE', answer: '已跳过' },
      ]);
      expect(state).toBe('completed');
    });

    it('awaiting_confirmation 记录 pendingConfirmation 上下文', () => {
      const actor = createActor(agentTaskMachine);
      actor.start();
      actor.send({ type: 'SUBMIT', taskId: 't1', sessionId: 's1', query: '执行代码' });
      actor.send({ type: 'TASK_STARTED' });
      actor.send({ type: 'PLAN_READY', plan: { steps: [], parallel_layers: [] } });
      actor.send({
        type: 'CONFIRMATION_REQUIRED',
        tool: 'write_file',
        args: { path: '/tmp/x', content: 'x' },
      });
      const snap = actor.getSnapshot();
      expect(snap.context.pendingConfirmation?.tool).toBe('write_file');
      expect(snap.context.pendingConfirmation?.args.path).toBe('/tmp/x');
    });

    it('CONFIRMED 后清空 pendingConfirmation', () => {
      const actor = createActor(agentTaskMachine);
      actor.start();
      actor.send({ type: 'SUBMIT', taskId: 't1', sessionId: 's1', query: '执行代码' });
      actor.send({ type: 'TASK_STARTED' });
      actor.send({ type: 'PLAN_READY', plan: { steps: [], parallel_layers: [] } });
      actor.send({ type: 'CONFIRMATION_REQUIRED', tool: 'write_file', args: {} });
      actor.send({ type: 'CONFIRMED' });
      const snap = actor.getSnapshot();
      expect(snap.context.pendingConfirmation).toBeNull();
    });
  });

  describe('失败路径', () => {
    it('pending → failed（rate_limited / guardrail_blocked）', () => {
      const state = runTaskMachine([
        { type: 'SUBMIT', taskId: 't1', sessionId: 's1', query: '恶意内容' },
        { type: 'TASK_FAILED', error: '护栏拦截', errorCode: 'GUARDRAIL_BLOCKED' },
      ]);
      expect(state).toBe('failed');
    });

    it('planning → failed（planner retry exhausted）', () => {
      const state = runTaskMachine([
        { type: 'SUBMIT', taskId: 't1', sessionId: 's1', query: '测试' },
        { type: 'TASK_STARTED' },
        { type: 'PLAN_FAILED', error: '规划失败' },
      ]);
      expect(state).toBe('failed');
    });

    it('running → failed（max_steps / timeout / llm_error）', () => {
      const state = runTaskMachine([
        { type: 'SUBMIT', taskId: 't1', sessionId: 's1', query: '测试' },
        { type: 'TASK_STARTED' },
        { type: 'PLAN_READY', plan: { steps: [], parallel_layers: [] } },
        { type: 'TASK_FAILED', error: '达到最大步数', errorCode: 'MAX_STEPS' },
      ]);
      expect(state).toBe('failed');
    });

    it('failed 状态记录 error 和 errorCode', () => {
      const actor = createActor(agentTaskMachine);
      actor.start();
      actor.send({ type: 'SUBMIT', taskId: 't1', sessionId: 's1', query: '测试' });
      actor.send({ type: 'TASK_FAILED', error: '超时', errorCode: 'TIMEOUT' });
      const snap = actor.getSnapshot();
      expect(snap.context.error).toBe('超时');
      expect(snap.context.errorCode).toBe('TIMEOUT');
    });

    it('PLAN_FAILED 设置 errorCode 为 PLANNER_FAILED', () => {
      const actor = createActor(agentTaskMachine);
      actor.start();
      actor.send({ type: 'SUBMIT', taskId: 't1', sessionId: 's1', query: '测试' });
      actor.send({ type: 'TASK_STARTED' });
      actor.send({ type: 'PLAN_FAILED', error: '规划重试耗尽' });
      const snap = actor.getSnapshot();
      expect(snap.context.errorCode).toBe('PLANNER_FAILED');
    });
  });

  describe('取消路径', () => {
    it('running → cancelled（用户 CANCEL）', () => {
      const state = runTaskMachine([
        { type: 'SUBMIT', taskId: 't1', sessionId: 's1', query: '测试' },
        { type: 'TASK_STARTED' },
        { type: 'PLAN_READY', plan: { steps: [], parallel_layers: [] } },
        { type: 'CANCEL' },
      ]);
      expect(state).toBe('cancelled');
    });

    it('running → cancelled（后端 TASK_CANCELLED）', () => {
      const state = runTaskMachine([
        { type: 'SUBMIT', taskId: 't1', sessionId: 's1', query: '测试' },
        { type: 'TASK_STARTED' },
        { type: 'PLAN_READY', plan: { steps: [], parallel_layers: [] } },
        { type: 'TASK_CANCELLED' },
      ]);
      expect(state).toBe('cancelled');
    });

    it('pending → cancelled（提交后立即取消）', () => {
      const state = runTaskMachine([
        { type: 'SUBMIT', taskId: 't1', sessionId: 's1', query: '测试' },
        { type: 'CANCEL' },
      ]);
      expect(state).toBe('cancelled');
    });

    it('planning → cancelled（规划阶段取消）', () => {
      const state = runTaskMachine([
        { type: 'SUBMIT', taskId: 't1', sessionId: 's1', query: '测试' },
        { type: 'TASK_STARTED' },
        { type: 'CANCEL' },
      ]);
      expect(state).toBe('cancelled');
    });
  });

  describe('RESET 重置', () => {
    it('failed → idle（RESET）', () => {
      const actor = createActor(agentTaskMachine);
      actor.start();
      actor.send({ type: 'SUBMIT', taskId: 't1', sessionId: 's1', query: '测试' });
      actor.send({ type: 'TASK_FAILED', error: '失败' });
      actor.send({ type: 'RESET' });
      const snap = actor.getSnapshot();
      expect(snap.value).toBe('idle');
      expect(snap.context.taskId).toBeNull();
      expect(snap.context.query).toBe('');
    });

    it('cancelled → idle（RESET）', () => {
      const actor = createActor(agentTaskMachine);
      actor.start();
      actor.send({ type: 'SUBMIT', taskId: 't1', sessionId: 's1', query: '测试' });
      actor.send({ type: 'CANCEL' });
      actor.send({ type: 'RESET' });
      expect(actor.getSnapshot().value).toBe('idle');
    });

    it('completed 是 final 状态，RESET 在全局 on 中仍可触发', () => {
      const actor = createActor(agentTaskMachine);
      actor.start();
      actor.send({ type: 'SUBMIT', taskId: 't1', sessionId: 's1', query: '测试' });
      actor.send({ type: 'TASK_STARTED' });
      actor.send({ type: 'PLAN_READY', plan: { steps: [], parallel_layers: [] } });
      actor.send({ type: 'FINAL_RESPONSE', answer: '答案' });
      expect(actor.getSnapshot().value).toBe('completed');
      actor.send({ type: 'RESET' });
      expect(actor.getSnapshot().value).toBe('idle');
    });
  });

  describe('上下文赋值', () => {
    it('SUBMIT 设置 taskId/sessionId/query/maxSteps', () => {
      const actor = createActor(agentTaskMachine);
      actor.start();
      actor.send({
        type: 'SUBMIT',
        taskId: 'task-abc',
        sessionId: 'sess-xyz',
        query: '查询靶点',
        maxSteps: 20,
      });
      const ctx = actor.getSnapshot().context;
      expect(ctx.taskId).toBe('task-abc');
      expect(ctx.sessionId).toBe('sess-xyz');
      expect(ctx.query).toBe('查询靶点');
      expect(ctx.maxSteps).toBe(20);
    });

    it('SUBMIT 默认 maxSteps=15', () => {
      const actor = createActor(agentTaskMachine);
      actor.start();
      actor.send({ type: 'SUBMIT', taskId: 't1', sessionId: 's1', query: '测试' });
      expect(actor.getSnapshot().context.maxSteps).toBe(15);
    });

    it('STEP_START 更新 currentStep', () => {
      const actor = createActor(agentTaskMachine);
      actor.start();
      actor.send({ type: 'SUBMIT', taskId: 't1', sessionId: 's1', query: '测试' });
      actor.send({ type: 'TASK_STARTED' });
      actor.send({ type: 'PLAN_READY', plan: { steps: [], parallel_layers: [] } });
      actor.send({ type: 'STEP_START', step: 3 });
      expect(actor.getSnapshot().context.currentStep).toBe(3);
    });

    it('PLAN_READY 设置 plan 到上下文', () => {
      const actor = createActor(agentTaskMachine);
      actor.start();
      actor.send({ type: 'SUBMIT', taskId: 't1', sessionId: 's1', query: '测试' });
      actor.send({ type: 'TASK_STARTED' });
      const plan = {
        steps: [{ id: 's1', tool: 'discover_targets', args: {}, depends_on: [] }],
        parallel_layers: [['s1']],
        reasoning: '先发现靶点',
      };
      actor.send({ type: 'PLAN_READY', plan });
      expect(actor.getSnapshot().context.plan).toEqual(plan);
    });
  });
});

describe('agentTaskMachine — 辅助函数', () => {
  describe('isTerminalStatus', () => {
    it('completed/failed/cancelled 返回 true', () => {
      expect(isTerminalStatus('completed')).toBe(true);
      expect(isTerminalStatus('failed')).toBe(true);
      expect(isTerminalStatus('cancelled')).toBe(true);
    });

    it('非终态返回 false', () => {
      expect(isTerminalStatus('pending')).toBe(false);
      expect(isTerminalStatus('planning')).toBe(false);
      expect(isTerminalStatus('running')).toBe(false);
      expect(isTerminalStatus('awaiting_confirmation')).toBe(false);
    });
  });

  describe('canSubmitTask', () => {
    it('idle/终态允许提交新任务', () => {
      expect(canSubmitTask('idle')).toBe(true);
      expect(canSubmitTask('completed')).toBe(true);
      expect(canSubmitTask('failed')).toBe(true);
      expect(canSubmitTask('cancelled')).toBe(true);
    });

    it('运行中状态不允许提交新任务', () => {
      expect(canSubmitTask('pending')).toBe(false);
      expect(canSubmitTask('planning')).toBe(false);
      expect(canSubmitTask('running')).toBe(false);
      expect(canSubmitTask('awaiting_confirmation')).toBe(false);
    });
  });

  describe('isRunningState', () => {
    it('pending/planning/running/awaiting_confirmation 返回 true', () => {
      expect(isRunningState('pending')).toBe(true);
      expect(isRunningState('planning')).toBe(true);
      expect(isRunningState('running')).toBe(true);
      expect(isRunningState('awaiting_confirmation')).toBe(true);
    });

    it('idle/终态返回 false', () => {
      expect(isRunningState('idle')).toBe(false);
      expect(isRunningState('completed')).toBe(false);
      expect(isRunningState('failed')).toBe(false);
      expect(isRunningState('cancelled')).toBe(false);
    });
  });
});
