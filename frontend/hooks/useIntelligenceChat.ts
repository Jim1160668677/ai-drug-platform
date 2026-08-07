'use client';

/**
 * useIntelligenceChat — 统一对话聚合 Hook
 *
 * 管理消息列表 + send/stream 切换，避免 UnifiedChatPanel 和
 * ChatStreamController 各自维护消息状态造成分裂。
 */
import { useState, useCallback } from 'react';
import { useMutation } from '@tanstack/react-query';
import { sendIntelligenceChat } from '@/lib/api';
import { useIntelligenceStream } from './useIntelligenceStream';
import type { ChatPayload, IntelligenceMessage, ChatResponse } from '@/types/intelligence';

export function useIntelligenceChat(sessionId: string) {
  const [messages, setMessages] = useState<IntelligenceMessage[]>([]);
  const [useStream, setUseStream] = useState(false);

  // 普通对话
  const chatMutation = useMutation({
    mutationFn: (payload: ChatPayload) =>
      sendIntelligenceChat(sessionId, payload.message, {
        projectId: payload.project_id,
        forceMode: payload.force_mode,
      }),
  });

  // 流式对话
  const stream = useIntelligenceStream({
    onDone: (fullText) => {
      // 流式结束后，将流式消息标记为完成
      setMessages((prev) =>
        prev.map((m) =>
          m.isStreaming
            ? {
                ...m,
                content: fullText,
                isStreaming: false,
              }
            : m,
        ),
      );
    },
    onError: (err) => {
      setMessages((prev) =>
        prev.map((m) =>
          m.isStreaming
            ? { ...m, content: `流式错误: ${err}`, isStreaming: false }
            : m,
        ),
      );
    },
  });

  const send = useCallback(
    async (message: string, projectId?: string, forceMode?: string) => {
      if (!message.trim() || !sessionId) return;

      const userMsg: IntelligenceMessage = {
        id: `msg-${Date.now()}-u`,
        role: 'user',
        content: message,
        timestamp: new Date().toISOString(),
      };

      const payload: ChatPayload = {
        message,
        project_id: projectId,
        force_mode: forceMode as ChatPayload['force_mode'],
      };

      if (useStream) {
        // 流式：先加 user 消息 + 占位 assistant 消息
        const assistantId = `msg-${Date.now()}-a`;
        const placeholder: IntelligenceMessage = {
          id: assistantId,
          role: 'assistant',
          content: '',
          timestamp: new Date().toISOString(),
          isStreaming: true,
        };
        setMessages((prev) => [...prev, userMsg, placeholder]);
        await stream.start(sessionId, payload);
      } else {
        // 普通：加 user 消息，等待响应
        setMessages((prev) => [...prev, userMsg]);
        try {
          const resp: ChatResponse = await chatMutation.mutateAsync(payload);
          const assistantMsg: IntelligenceMessage = {
            id: `msg-${Date.now()}-a`,
            role: 'assistant',
            content: resp.answer,
            mode: resp.mode,
            intent: resp.intent,
            cost_usd: resp.cost_usd,
            duration_sec: resp.duration_sec,
            timestamp: new Date().toISOString(),
          };
          setMessages((prev) => [...prev, assistantMsg]);
        } catch (err) {
          const errMsg: IntelligenceMessage = {
            id: `msg-${Date.now()}-e`,
            role: 'system',
            content: `错误: ${err instanceof Error ? err.message : String(err)}`,
            timestamp: new Date().toISOString(),
          };
          setMessages((prev) => [...prev, errMsg]);
        }
      }
    },
    [sessionId, useStream, stream, chatMutation],
  );

  // 流式过程中实时更新 assistant 消息
  const streamingText = stream.streamingText;
  if (stream.status === 'streaming' && streamingText) {
    // 同步流式文本到消息列表
    setMessages((prev) =>
      prev.map((m) =>
        m.isStreaming ? { ...m, content: streamingText } : m,
      ),
    );
  }

  const clearMessages = useCallback(() => setMessages([]), []);

  return {
    messages,
    send,
    clearMessages,
    isSending: chatMutation.isPending || stream.status === 'streaming',
    useStream,
    setUseStream,
    streamStatus: stream.status,
    abortStream: stream.abort,
  };
}
