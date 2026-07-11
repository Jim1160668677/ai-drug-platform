'use client';

import { useState } from 'react';
import { useMutation } from '@tanstack/react-query';
import { chat, analyze } from '@/lib/api';
import type { Message, TiersData, AnalysisResult } from '@/types/chat';

export function useChatState(projectId: string | undefined) {
  const [messages, setMessages] = useState<Message[]>([]);
  const [input, setInput] = useState('');
  const [tier, setTier] = useState('fast_screen');
  const [tiers, setTiers] = useState<TiersData | null>(null);
  const [analysis, setAnalysis] = useState<AnalysisResult | null>(null);

  const chatMutation = useMutation({
    mutationFn: (msg: string) => chat({ message: msg, projectId, tier }),
    onSuccess: (data) => {
      setMessages((m) => [
        ...m,
        {
          role: 'assistant',
          content: data.answer || '（无回复）',
          tier: data.tier,
          cost: data.cost_usd,
          duration: data.duration_sec,
          model: data.model,
          references: data.references,
          code: data.code,
        },
      ]);
    },
    onError: (err: any) => {
      setMessages((m) => [
        ...m,
        {
          role: 'assistant',
          content: `请求失败：${err.response?.data?.detail || err.message}`,
        },
      ]);
    },
  });

  const analyzeMutation = useMutation({
    mutationFn: (msg: string) =>
      analyze({ message: msg, projectId: projectId!, tier }),
    onSuccess: (data) => {
      setAnalysis(data?.data || data);
    },
  });

  const sendMessage = () => {
    const msg = input.trim();
    if (!msg) return;
    setMessages((m) => [...m, { role: 'user', content: msg }]);
    chatMutation.mutate(msg);
    setInput('');
  };

  const analyzeMessage = () => {
    const msg = input.trim();
    if (!msg || !projectId) return;
    setMessages((m) => [...m, { role: 'user', content: `【深度分析】${msg}` }]);
    analyzeMutation.mutate(msg);
    setInput('');
  };

  return {
    messages,
    input,
    tier,
    tiers,
    analysis,
    isSending: chatMutation.isPending,
    isAnalyzing: analyzeMutation.isPending,
    setInput,
    setTier,
    setTiers,
    sendMessage,
    analyzeMessage,
  };
}
