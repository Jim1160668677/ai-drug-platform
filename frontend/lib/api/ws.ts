/**
 * WebSocket 基础客户端 — 任务进度实时推送
 *
 * 后端端点：app/api/v1/endpoints/ws.py
 * - WS:  /api/v1/ws/tasks/{task_id}?token=xxx（JWT 握手校验）
 * - HTTP: /api/v1/tasks/{task_id}/status（轮询回退）
 *
 * 特性：
 * - 自动重连（指数退避，最多 5 次）
 * - 心跳保活（30 秒 ping）
 * - 3 次 WS 失败后降级到 HTTP 轮询
 */
import type { TaskProgress } from '@/types/api';

const API_BASE = process.env.NEXT_PUBLIC_API_BASE || 'http://localhost:8000/api/v1';

// 从 HTTP API URL 推导 WebSocket URL
function buildWsBaseUrl(): string {
  const base = API_BASE.replace(/^http:/, 'ws:').replace(/^https:/, 'wss:');
  return base;
}

export const WS_BASE = buildWsBaseUrl();

export interface TaskProgressClientOptions {
  /** 重连最大次数（默认 5） */
  maxRetries?: number;
  /** 初始重连延迟（毫秒，默认 1000） */
  initialRetryDelay?: number;
  /** 心跳间隔（毫秒，默认 30000） */
  heartbeatInterval?: number;
  /** HTTP 轮询间隔（毫秒，默认 2000） */
  pollInterval?: number;
}

export interface TaskProgressCallbacks {
  onProgress?: (progress: TaskProgress) => void;
  onConnected?: () => void;
  onDisconnected?: () => void;
  onError?: (error: Event) => void;
}

/**
 * TaskProgressClient — 单任务进度订阅客户端
 *
 * 用法：
 * const client = new TaskProgressClient(taskId, token, callbacks);
 * client.connect();
 * // ...
 * client.disconnect();
 */
export class TaskProgressClient {
  private ws: WebSocket | null = null;
  private taskId: string;
  private token: string;
  private callbacks: TaskProgressCallbacks;
  private options: Required<TaskProgressClientOptions>;
  private retryCount = 0;
  private retryTimer: ReturnType<typeof setTimeout> | null = null;
  private heartbeatTimer: ReturnType<typeof setInterval> | null = null;
  private pollTimer: ReturnType<typeof setInterval> | null = null;
  private fallbackToPolling = false;
  private terminalStatuses = new Set(['completed', 'failed']);
  private disposed = false;

  constructor(
    taskId: string,
    token: string,
    callbacks: TaskProgressCallbacks = {},
    options: TaskProgressClientOptions = {},
  ) {
    this.taskId = taskId;
    this.token = token;
    this.callbacks = callbacks;
    this.options = {
      maxRetries: options.maxRetries ?? 5,
      initialRetryDelay: options.initialRetryDelay ?? 1000,
      heartbeatInterval: options.heartbeatInterval ?? 30000,
      pollInterval: options.pollInterval ?? 2000,
    };
  }

  /** 建立 WebSocket 连接 */
  connect(): void {
    if (this.disposed) return;

    const wsUrl = `${WS_BASE}/ws/tasks/${this.taskId}?token=${encodeURIComponent(this.token)}`;
    try {
      this.ws = new WebSocket(wsUrl);
    } catch (err) {
      console.error('[WS] 构造失败，降级到轮询:', err);
      this.startPolling();
      return;
    }

    this.ws.onopen = () => {
      this.retryCount = 0;
      this.fallbackToPolling = false;
      this.callbacks.onConnected?.();
      this.startHeartbeat();
    };

    this.ws.onmessage = (event) => {
      try {
        const data: TaskProgress = JSON.parse(event.data);
        this.callbacks.onProgress?.(data);
        if (this.terminalStatuses.has(data.status)) {
          this.disconnect();
        }
      } catch (err) {
        console.warn('[WS] 消息解析失败:', err);
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
    this.stopPolling();
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

  /** 调度重连（指数退避） */
  private scheduleReconnect(): void {
    if (this.retryCount >= this.options.maxRetries) {
      // 超过最大重试次数，降级到 HTTP 轮询
      this.startPolling();
      return;
    }

    const delay = this.options.initialRetryDelay * Math.pow(2, this.retryCount);
    this.retryCount += 1;
    this.retryTimer = setTimeout(() => {
      if (!this.disposed) {
        this.connect();
      }
    }, delay);
  }

  /** 启动心跳 */
  private startHeartbeat(): void {
    this.heartbeatTimer = setInterval(() => {
      if (this.ws && this.ws.readyState === WebSocket.OPEN) {
        try {
          this.ws.send(JSON.stringify({ type: 'ping' }));
        } catch {
          // 忽略发送失败
        }
      }
    }, this.options.heartbeatInterval);
  }

  /** 停止心跳 */
  private stopHeartbeat(): void {
    if (this.heartbeatTimer) {
      clearInterval(this.heartbeatTimer);
      this.heartbeatTimer = null;
    }
  }

  /** 降级到 HTTP 轮询 */
  private startPolling(): void {
    if (this.fallbackToPolling || this.disposed) return;
    this.fallbackToPolling = true;
    console.info('[WS] 降级到 HTTP 轮询');

    const poll = async () => {
      if (this.disposed) return;
      try {
        const API_BASE_HTTP = process.env.NEXT_PUBLIC_API_BASE || 'http://localhost:8000/api/v1';
        const resp = await fetch(`${API_BASE_HTTP}/tasks/${this.taskId}/status`, {
          headers: { Authorization: `Bearer ${this.token}` },
        });
        if (resp.ok) {
          const payload = await resp.json();
          const data = payload?.data ?? payload;
          this.callbacks.onProgress?.(data as TaskProgress);
          if (this.terminalStatuses.has(data.status)) {
            this.stopPolling();
            return;
          }
        }
      } catch (err) {
        console.warn('[WS] 轮询失败:', err);
      }
    };

    poll(); // 立即执行一次
    this.pollTimer = setInterval(poll, this.options.pollInterval);
  }

  /** 停止轮询 */
  private stopPolling(): void {
    if (this.pollTimer) {
      clearInterval(this.pollTimer);
      this.pollTimer = null;
    }
  }
}
