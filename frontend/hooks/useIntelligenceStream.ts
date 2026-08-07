'use client';

/**
 * useIntelligenceStream — SSE 流式对话 Hook
 *
 * 封装 streamChat，管理流式状态（idle/streaming/done/error），
 * 提供 onStart/onChunk/onDone/onError 回调。
 */
import { useState, useRef, useCallback } from 'react';
import { streamChat, type StreamCallbacks } from '@/lib/api';
import type { ChatPayload } from '@/types/intelligence';

export type StreamStatus = 'idle' | 'streaming' | 'done' | 'error';

interface UseIntelligenceStreamOptions {
  onChunk?: (chunk: string, fullText: string) => void;
  onDone?: (fullText: string) => void;
  onError?: (err: string) => void;
}

export function useIntelligenceStream(options: UseIntelligenceStreamOptions = {}) {
  const [status, setStatus] = useState<StreamStatus>('idle');
  const [streamingText, setStreamingText] = useState('');
  const [error, setError] = useState<string | null>(null);
  const abortRef = useRef<boolean>(false);

  const start = useCallback(
    async (sessionId: string, payload: ChatPayload) => {
      setStatus('streaming');
      setStreamingText('');
      setError(null);
      abortRef.current = false;

      let full = '';
      const callbacks: StreamCallbacks = {
        onChunk: (chunk) => {
          if (abortRef.current) return;
          full += chunk;
          setStreamingText(full);
          options.onChunk?.(chunk, full);
        },
        onDone: (fullText) => {
          if (abortRef.current) return;
          setStatus('done');
          setStreamingText(fullText);
          options.onDone?.(fullText);
        },
        onError: (err) => {
          if (abortRef.current) return;
          setStatus('error');
          setError(err);
          options.onError?.(err);
        },
      };

      try {
        await streamChat(sessionId, payload.message, {
          projectId: payload.project_id,
          forceMode: payload.force_mode,
          ...callbacks,
        });
      } catch (err) {
        setStatus('error');
        const msg = err instanceof Error ? err.message : String(err);
        setError(msg);
        options.onError?.(msg);
      }
    },
    [options],
  );

  const abort = useCallback(() => {
    abortRef.current = true;
    setStatus('idle');
    setStreamingText('');
  }, []);

  const reset = useCallback(() => {
    setStatus('idle');
    setStreamingText('');
    setError(null);
    abortRef.current = false;
  }, []);

  return { status, streamingText, error, start, abort, reset };
}
