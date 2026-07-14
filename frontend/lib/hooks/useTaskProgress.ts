/**
 * useTaskProgress — 任务进度实时订阅 Hook
 *
 * 封装 TaskProgressClient，提供声明式的进度订阅接口。
 *
 * 用法：
 * const { progress, connected, error } = useTaskProgress(taskId);
 *
 * 特性：
 * - taskId 为 null 时不建立连接
 * - 自动在组件卸载时断开连接
 * - WebSocket 失败后自动降级到 HTTP 轮询
 */
import { useEffect, useState, useRef } from 'react';
import { TaskProgressClient } from '@/lib/api/ws';
import type { TaskProgress } from '@/types/api';

export interface UseTaskProgressResult {
  /** 当前任务进度（null 表示尚未收到） */
  progress: TaskProgress | null;
  /** WebSocket 是否已连接（轮询模式下为 false） */
  connected: boolean;
  /** 连接错误 */
  error: Event | null;
}

export function useTaskProgress(taskId: string | null): UseTaskProgressResult {
  const [progress, setProgress] = useState<TaskProgress | null>(null);
  const [connected, setConnected] = useState(false);
  const [error, setError] = useState<Event | null>(null);
  const clientRef = useRef<TaskProgressClient | null>(null);

  useEffect(() => {
    if (!taskId) {
      setProgress(null);
      setConnected(false);
      setError(null);
      return;
    }

    if (typeof window === 'undefined') return;

    const token = localStorage.getItem('ai_drug_token');
    if (!token) {
      console.warn('[useTaskProgress] 缺少 JWT token');
      return;
    }

    const client = new TaskProgressClient(taskId, token, {
      onProgress: (p) => setProgress(p),
      onConnected: () => {
        setConnected(true);
        setError(null);
      },
      onDisconnected: () => setConnected(false),
      onError: (e) => setError(e),
    });

    clientRef.current = client;
    client.connect();

    return () => {
      client.disconnect();
      clientRef.current = null;
    };
  }, [taskId]);

  return { progress, connected, error };
}
