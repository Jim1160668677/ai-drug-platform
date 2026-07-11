export interface Message {
  role: 'user' | 'assistant';
  content: string;
  tier?: string;
  cost?: number;
  duration?: number;
  model?: string;
  references?: any[];
  code?: string;
  charts?: any[];
}

export interface Tier {
  name: string;
  label: string;
  tech_stack: string;
  max_cost_usd: number;
  max_duration_sec: number;
}

export interface TiersData {
  tiers: Tier[];
}

export interface AnalysisResult {
  report?: string;
  conclusion?: string;
  code?: string;
  references?: Array<{ title?: string } | string>;
}
