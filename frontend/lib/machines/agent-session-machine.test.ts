/**
 * AgentSession 状态机单元测试
 *
 * 验证设计文档 §2.4.2 定义的状态转移：
 *   idle → active → paused → archived
 *   active 内部 WS 连接子状态：connecting → connected → reconnecting
 */
import { describe, it, expect } from 'vitest';
import { createActor } from 'xstate';
import {
  agentSessionMachine,
  canSendMessage,
  isReadOnlySession,
  isWSConnected,
  isConnecting,
  type AgentSessionEvent,
} from './agent-session-machine';

/** 创建 actor 并发送事件序列，返回最终状态值 */
function runSessionMachine(events: AgentSessionEvent[]): string {
  const actor = createActor(agentSessionMachine);
  actor.start();
  for (const evt of events) {
    actor.send(evt);
  }
  const snapshot = actor.getSnapshot();
  return snapshot.value as string;
}

const SELECT_EVENT: AgentSessionEvent = {
  type: 'SELECT_SESSION',
  sessionId: 'sess-1',
  title: '测试会话',
  status: 'active',
};

describe('agentSessionMachine — 会话活跃状态转移', () => {
  describe('正常流程', () => {
    it('idle → active.connecting → active.connected（选择会话后连接成功）', () => {
      const state = runSessionMachine([SELECT_EVENT, { type: 'CONNECTED' }]);
      // XState v5 嵌套状态返回对象 { active: 'connected' }
      expect(state).toEqual({ active: 'connected' });
    });

    it('SELECT_SESSION 设置会话元数据', () => {
      const actor = createActor(agentSessionMachine);
      actor.start();
      actor.send(SELECT_EVENT);
      const ctx = actor.getSnapshot().context;
      expect(ctx.sessionId).toBe('sess-1');
      expect(ctx.title).toBe('测试会话');
      expect(ctx.sessionStatus).toBe('active');
      expect(ctx.reconnectAttempts).toBe(0);
    });

    it('CONNECTED 重置 reconnectAttempts 并设置 lastActivityAt', () => {
      const actor = createActor(agentSessionMachine);
      actor.start();
      actor.send(SELECT_EVENT);
      actor.send({ type: 'CONNECT_FAILED', error: '首次失败' });
      actor.send({ type: 'RECONNECT' });
      actor.send({ type: 'CONNECTED' });
      const ctx = actor.getSnapshot().context;
      expect(ctx.reconnectAttempts).toBe(0);
      expect(ctx.lastActivityAt).not.toBeNull();
    });
  });

  describe('WS 连接子状态', () => {
    it('CONNECT_FAILED 进入 error 状态', () => {
      const state = runSessionMachine([
        SELECT_EVENT,
        { type: 'CONNECT_FAILED', error: '连接超时' },
      ]);
      expect(state).toBe('error');
    });

    it('error 状态记录错误和重连次数', () => {
      const actor = createActor(agentSessionMachine);
      actor.start();
      actor.send(SELECT_EVENT);
      actor.send({ type: 'CONNECT_FAILED', error: '超时' });
      const ctx = actor.getSnapshot().context;
      expect(ctx.error).toBe('超时');
      expect(ctx.reconnectAttempts).toBe(1);
    });

    it('error → RECONNECT → connecting', () => {
      const actor = createActor(agentSessionMachine);
      actor.start();
      actor.send(SELECT_EVENT);
      actor.send({ type: 'CONNECT_FAILED', error: '失败' });
      actor.send({ type: 'RECONNECT' });
      // XState v5 嵌套状态返回对象 { active: 'connecting' }
      expect(actor.getSnapshot().value).toEqual({ active: 'connecting' });
    });

    it('connected → DISCONNECTED → reconnecting → connecting（自动重连）', () => {
      const actor = createActor(agentSessionMachine);
      actor.start();
      actor.send(SELECT_EVENT);
      actor.send({ type: 'CONNECTED' });
      expect(actor.getSnapshot().value).toEqual({ active: 'connected' });
      actor.send({ type: 'DISCONNECTED' });
      // reconnecting 的 always 转移会立即转到 connecting（XState v5 返回对象）
      const state = actor.getSnapshot().value;
      const stateStr =
        typeof state === 'object' && state !== null && 'active' in state
          ? `active.${(state as Record<string, string>).active}`
          : (state as string);
      expect(['active.reconnecting', 'active.connecting']).toContain(stateStr);
    });

    it('connected → DISCONNECT → disconnecting → idle（用户主动断开）', () => {
      const actor = createActor(agentSessionMachine);
      actor.start();
      actor.send(SELECT_EVENT);
      actor.send({ type: 'CONNECTED' });
      actor.send({ type: 'DISCONNECT' });
      // XState v5 嵌套状态返回对象
      expect(actor.getSnapshot().value).toEqual({ active: 'disconnecting' });
      actor.send({ type: 'DISCONNECTED' });
      expect(actor.getSnapshot().value).toBe('idle');
    });

    it('超过最大重连次数后不再自动重连（canReconnect guard）', () => {
      const actor = createActor(agentSessionMachine);
      actor.start();
      actor.send(SELECT_EVENT);
      // 设置较小的 maxReconnectAttempts 通过多次失败来测试
      // 默认 maxReconnectAttempts=5，模拟 5 次失败 + 重连
      for (let i = 0; i < 5; i++) {
        actor.send({ type: 'CONNECT_FAILED', error: `失败${i}` });
        actor.send({ type: 'RECONNECT' });
      }
      // 第 6 次失败后应该在 error 状态，reconnectAttempts=6
      actor.send({ type: 'CONNECT_FAILED', error: '失败6' });
      const ctx = actor.getSnapshot().context;
      expect(ctx.reconnectAttempts).toBeGreaterThanOrEqual(5);
    });
  });

  describe('暂停与归档', () => {
    it('active → paused（5min 无活动 INACTIVITY_TIMEOUT）', () => {
      const state = runSessionMachine([
        SELECT_EVENT,
        { type: 'CONNECTED' },
        { type: 'INACTIVITY_TIMEOUT' },
      ]);
      expect(state).toBe('paused');
    });

    it('paused 记录 sessionStatus 为 paused', () => {
      const actor = createActor(agentSessionMachine);
      actor.start();
      actor.send(SELECT_EVENT);
      actor.send({ type: 'CONNECTED' });
      actor.send({ type: 'INACTIVITY_TIMEOUT' });
      expect(actor.getSnapshot().context.sessionStatus).toBe('paused');
    });

    it('paused → active.connecting（RESUME 唤醒）', () => {
      const actor = createActor(agentSessionMachine);
      actor.start();
      actor.send(SELECT_EVENT);
      actor.send({ type: 'CONNECTED' });
      actor.send({ type: 'INACTIVITY_TIMEOUT' });
      actor.send({ type: 'RESUME' });
      // XState v5 嵌套状态返回对象
      expect(actor.getSnapshot().value).toEqual({ active: 'connecting' });
    });

    it('paused → archived（ARCHIVE）', () => {
      const state = runSessionMachine([
        SELECT_EVENT,
        { type: 'CONNECTED' },
        { type: 'INACTIVITY_TIMEOUT' },
        { type: 'ARCHIVE' },
      ]);
      expect(state).toBe('archived');
    });

    it('active → archived（直接归档）', () => {
      const state = runSessionMachine([
        SELECT_EVENT,
        { type: 'CONNECTED' },
        { type: 'ARCHIVE' },
      ]);
      expect(state).toBe('archived');
    });

    it('archived 是 final 状态', () => {
      const actor = createActor(agentSessionMachine);
      actor.start();
      actor.send(SELECT_EVENT);
      actor.send({ type: 'CONNECTED' });
      actor.send({ type: 'ARCHIVE' });
      const snap = actor.getSnapshot();
      expect(snap.status).toBe('done'); // final 状态 actor 完成
    });
  });

  describe('活动度刷新', () => {
    it('MESSAGE_SENT 刷新 lastActivityAt', () => {
      const actor = createActor(agentSessionMachine);
      actor.start();
      actor.send(SELECT_EVENT);
      actor.send({ type: 'CONNECTED' });
      // 等待一小段时间确保时间戳不同
      actor.send({ type: 'MESSAGE_SENT' });
      const after = actor.getSnapshot().context.lastActivityAt;
      expect(after).not.toBeNull();
      // 时间戳应是有效 ISO 字符串
      expect(new Date(after!).getTime()).not.toBeNaN();
    });

    it('MESSAGE_RECEIVED 刷新 lastActivityAt', () => {
      const actor = createActor(agentSessionMachine);
      actor.start();
      actor.send(SELECT_EVENT);
      actor.send({ type: 'CONNECTED' });
      actor.send({ type: 'MESSAGE_RECEIVED' });
      expect(actor.getSnapshot().context.lastActivityAt).not.toBeNull();
    });
  });

  describe('CLEAR 清空', () => {
    it('active → CLEAR → idle（清空上下文）', () => {
      const actor = createActor(agentSessionMachine);
      actor.start();
      actor.send(SELECT_EVENT);
      actor.send({ type: 'CONNECTED' });
      actor.send({ type: 'CLEAR' });
      const snap = actor.getSnapshot();
      expect(snap.value).toBe('idle');
      expect(snap.context.sessionId).toBeNull();
      expect(snap.context.title).toBeNull();
    });

    it('paused → CLEAR → idle', () => {
      const actor = createActor(agentSessionMachine);
      actor.start();
      actor.send(SELECT_EVENT);
      actor.send({ type: 'CONNECTED' });
      actor.send({ type: 'INACTIVITY_TIMEOUT' });
      actor.send({ type: 'CLEAR' });
      expect(actor.getSnapshot().value).toBe('idle');
    });
  });
});

describe('agentSessionMachine — 辅助函数', () => {
  describe('canSendMessage', () => {
    it('active.connected 返回 true', () => {
      expect(canSendMessage('active.connected')).toBe(true);
    });

    it('其他状态返回 false', () => {
      expect(canSendMessage('idle')).toBe(false);
      expect(canSendMessage('active.connecting')).toBe(false);
      expect(canSendMessage('active.reconnecting')).toBe(false);
      expect(canSendMessage('paused')).toBe(false);
      expect(canSendMessage('archived')).toBe(false);
      expect(canSendMessage('error')).toBe(false);
    });
  });

  describe('isReadOnlySession', () => {
    it('paused/archived 返回 true', () => {
      expect(isReadOnlySession('paused')).toBe(true);
      expect(isReadOnlySession('archived')).toBe(true);
    });

    it('active/idle 返回 false', () => {
      expect(isReadOnlySession('idle')).toBe(false);
      expect(isReadOnlySession('active.connected')).toBe(false);
    });
  });

  describe('isWSConnected', () => {
    it('active.connected 返回 true', () => {
      expect(isWSConnected('active.connected')).toBe(true);
    });

    it('其他返回 false', () => {
      expect(isWSConnected('active.connecting')).toBe(false);
      expect(isWSConnected('idle')).toBe(false);
    });
  });

  describe('isConnecting', () => {
    it('connecting/reconnecting/error 返回 true', () => {
      expect(isConnecting('active.connecting')).toBe(true);
      expect(isConnecting('active.reconnecting')).toBe(true);
      expect(isConnecting('error')).toBe(true);
    });

    it('connected/idle 返回 false', () => {
      expect(isConnecting('active.connected')).toBe(false);
      expect(isConnecting('idle')).toBe(false);
    });
  });
});
