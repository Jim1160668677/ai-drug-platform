import { api } from './client';

// ========== 药物可开发性评估 ==========

export interface ToxicityAlert {
  name: string;
  smarts: string;
  severity: 'warning' | 'danger';
}

export interface CostBreakdown {
  materials: number;
  labor: number;
  overhead: number;
}

export interface DevelopabilityAssessment {
  id: string;
  molecule_id: string;
  project_id: string | null;
  version: number;
  // 5 维度评分
  sa_score: number; // 1-10，越低越易合成
  sa_ease_label: 'easy' | 'medium' | 'hard';
  toxicity_risk: 'low' | 'moderate' | 'high';
  toxicity_alerts: ToxicityAlert[];
  formulation_score: number; // 0-1
  formulation_notes: string;
  cost_estimate_usd: number;
  cost_breakdown: CostBreakdown;
  // 综合
  overall_score: number; // 0-1
  recommendation: 'go' | 'revise' | 'no_go';
  rationale: string;
  created_at: string;
}

/** 触发药物可开发性评估（5 维度：合成/毒理/制剂/成本/综合） */
export const assessDevelopability = (moleculeId: string) =>
  api.post(`/molecules/${moleculeId}/assess-developability`).then((r) => r.data as DevelopabilityAssessment);

/** 查询分子的历史可开发性评估记录（按版本倒序） */
export const listDevelopability = (moleculeId: string) =>
  api.get(`/molecules/${moleculeId}/developability`).then((r) => r.data as DevelopabilityAssessment[]);

// ========== 常量标签 ==========

export const SA_EASE_LABELS: Record<string, string> = {
  easy: '易合成',
  medium: '中等',
  hard: '难合成',
};

export const TOXICITY_RISK_LABELS: Record<string, string> = {
  low: '低风险',
  moderate: '中风险',
  high: '高风险',
};

export const RECOMMENDATION_LABELS: Record<string, string> = {
  go: '通过（可推进）',
  revise: '需优化',
  no_go: '不建议推进',
};

export const RECOMMENDATION_COLORS: Record<string, string> = {
  go: 'bg-green-100 text-green-800 border-green-300',
  revise: 'bg-yellow-100 text-yellow-800 border-yellow-300',
  no_go: 'bg-red-100 text-red-800 border-red-300',
};
