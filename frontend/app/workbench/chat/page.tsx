'use client';

import { useEffect, useRef } from 'react';
import { useChatState } from '@/hooks/useChatState';
import { useAppStore } from '@/lib/store';
import { getTiers } from '@/lib/api';
import Card from '@/components/ui/Card';
import { TierSelector } from '@/components/chat/TierSelector';
import { MessageList } from '@/components/chat/MessageList';
import { ChatInput } from '@/components/chat/ChatInput';
import { AnalysisResultCard } from '@/components/chat/AnalysisResult';

export default function ChatPage() {
  const { currentProject } = useAppStore();
  const {
    messages,
    input,
    tier,
    tiers,
    analysis,
    isSending,
    isAnalyzing,
    setInput,
    setTier,
    setTiers,
    sendMessage,
    analyzeMessage,
  } = useChatState(currentProject?.id);

  const messagesEndRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    getTiers().then((d) => setTiers(d?.data)).catch(() => {});
  }, [setTiers]);

  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [messages]);

  return (
    <div className="space-y-4 h-full flex flex-col">
      <div>
        <h1 className="text-2xl font-bold">AI 问答</h1>
        <p className="text-sm text-gray-500 mt-1">
          复现 Sid 团队流程：研究者提问 → AI 自动执行分析 → 返回报告 + 代码 + 引用
        </p>
      </div>

      <TierSelector tiers={tiers} selectedTier={tier} onTierSelect={setTier} />

      <Card className="flex-1 overflow-hidden flex flex-col">
        <MessageList messages={messages} messagesEndRef={messagesEndRef} />
        <ChatInput
          input={input}
          onInputChange={setInput}
          onSend={sendMessage}
          onAnalyze={analyzeMessage}
          isSending={isSending}
          isAnalyzing={isAnalyzing}
          canAnalyze={!!currentProject}
        />
      </Card>

      <AnalysisResultCard analysis={analysis} />
    </div>
  );
}
