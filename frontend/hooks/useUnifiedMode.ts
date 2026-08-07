'use client';

import { useCallback, useEffect, useState } from 'react';
import { useIntelligenceChat } from './useIntelligenceChat';
import { useChatState } from './useChatState';
import { useAgentState } from './useAgentState';
import { useAppStore } from '@/lib/store';

export type IntelligenceMode = 'assistant' | 'qa' | 'agent';

const MODE_STORAGE_KEY = 'ai-drug:unified-intelligence-mode';

export function useUnifiedMode(initialMode?: IntelligenceMode) {
  const { currentProject } = useAppStore();

  const [mode, setMode] = useState<IntelligenceMode>(() => {
    if (initialMode) return initialMode;
    if (typeof window !== 'undefined') {
      const saved = localStorage.getItem(MODE_STORAGE_KEY) as IntelligenceMode | null;
      if (saved && ['assistant', 'qa', 'agent'].includes(saved)) {
        return saved;
      }
    }
    return 'assistant';
  });

  useEffect(() => {
    if (typeof window !== 'undefined') {
      localStorage.setItem(MODE_STORAGE_KEY, mode);
    }
  }, [mode]);

  const [sessionId, setSessionId] = useState<string>('');

  const intelligenceChat = useIntelligenceChat(sessionId);
  const chatState = useChatState(currentProject?.id);
  const agentState = useAgentState();

  const selectMode = useCallback((newMode: IntelligenceMode) => {
    setMode(newMode);
  }, []);

  const selectSession = useCallback((id: string) => {
    setSessionId(id);
  }, []);

  return {
    mode,
    setMode: selectMode,
    sessionId,
    setSessionId: selectSession,
    currentProject,
    intelligence: intelligenceChat,
    chat: chatState,
    agent: agentState,
  };
}
