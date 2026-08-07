/**
 * 统一智能系统类型定义
 */
export type PrimaryMode = 'chat' | 'reasoning' | 'agent' | 'hybrid' | 'auto';

export interface ChatPayload {
  message: string;
  project_id?: string;
  force_mode?: PrimaryMode;
}

export interface IntelligenceMessage {
  id: string;
  role: 'user' | 'assistant' | 'system';
  content: string;
  timestamp?: string;
  mode?: string;
  intent?: string;
  cost_usd?: number;
  duration_sec?: number;
  isStreaming?: boolean;
}

export type { ChatResponse } from '@/lib/api/intelligence';
