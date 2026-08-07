import { api } from './client';

// ========== 类型定义 ==========

export type SynthesisFeasibility = 'easy' | 'medium' | 'hard';

export interface SynthesisStep {
  step: number;
  reaction: string;
  reagents?: string[];
  conditions?: string;
}

export interface SynthesisRoute {
  route_id?: number;
  steps: SynthesisStep[];
  n_steps?: number;
  total_yield_estimate?: number;
  source?: string;
}

export interface FeasibilityResult {
  sa_score: number;
  sc_score?: number;
  feasibility_label: SynthesisFeasibility;
  challenges?: Array<{
    name: string;
    severity: 'low' | 'medium' | 'high';
    mitigation?: string;
  }>;
  n_steps?: number;
}

export interface CostBreakdown {
  materials: number;
  labor: number;
  equipment: number;
  overhead: number;
}

export interface CostEstimate {
  total_cost_usd: number;
  breakdown: CostBreakdown;
  cost_per_gram: number;
  is_cost_effective?: boolean;
  warning?: string;
  target_scale_grams?: number;
}

export interface SynthesisPlanInput {
  smiles: string;
  max_routes?: number;
  target_scale_grams?: number;
  molecule_id?: string;
  project_id?: string;
  molecule_name?: string;
}

export interface SynthesisPlanResult {
  plan_id: string;
  smiles: string;
  routes: SynthesisRoute[];
  n_routes: number;
  n_steps_best?: number;
  sa_score?: number;
  sc_score?: number;
  feasibility_label?: SynthesisFeasibility;
  challenges?: FeasibilityResult['challenges'];
  total_cost_usd?: number;
  cost_per_gram?: number;
  cost_breakdown?: CostBreakdown;
  is_cost_effective?: boolean;
  warning?: string;
  source_engine?: string;
  recommendation?: string;
  risk_assessment?: string;
  recommended_route_idx?: number | null;
}

export interface SynthesisPlanRecord {
  id: string;
  smiles: string;
  molecule_id: string | null;
  project_id: string | null;
  molecule_name: string | null;
  n_routes: number;
  n_steps_best: number | null;
  sa_score: number | null;
  sc_score: number | null;
  feasibility_label: SynthesisFeasibility | null;
  total_cost_usd: number | null;
  cost_per_gram: number | null;
  source_engine: string | null;
  created_at: string | null;
}

export interface SynthesisEngineInfo {
  name: string;
  available: boolean;
  mode: string;
}

// ========== API 调用 ==========

export const planSynthesis = (data: SynthesisPlanInput) =>
  api.post('/synthesis/plan', data).then((r) => r.data as SynthesisPlanResult);

export const listSynthesisPlans = (params: { page?: number; page_size?: number } = {}) =>
  api
    .get('/synthesis/plans', {
      params: { page: params.page ?? 1, page_size: params.page_size ?? 20 },
    })
    .then((r) => r.data);

export const getSynthesisPlan = (id: string) =>
  api.get(`/synthesis/plans/${id}`).then((r) => r.data as SynthesisPlanResult);

export const generateRoutes = (smiles: string, max_routes: number = 5) =>
  api
    .post('/synthesis/routes', { smiles, max_routes })
    .then((r) => r.data as { routes: SynthesisRoute[]; n_routes: number; source: string });

export const predictFeasibility = (data: { smiles: string; routes: SynthesisRoute[] }) =>
  api.post('/synthesis/feasibility', data).then((r) => r.data as FeasibilityResult);

export const estimateCost = (data: {
  routes: SynthesisRoute[];
  sa_score?: number;
  target_scale_grams?: number;
}) => api.post('/synthesis/cost', data).then((r) => r.data as CostEstimate);

export const listSynthesisEngines = () =>
  api.get('/synthesis/engines').then((r) => r.data as SynthesisEngineInfo[]);

// ========== 常量标签 ==========

export const FEASIBILITY_LABELS: Record<SynthesisFeasibility, string> = {
  easy: '易合成',
  medium: '中等难度',
  hard: '难合成',
};

export const FEASIBILITY_COLORS: Record<SynthesisFeasibility, string> = {
  easy: 'bg-green-100 text-green-700 border-green-300',
  medium: 'bg-amber-100 text-amber-700 border-amber-300',
  hard: 'bg-red-100 text-red-700 border-red-300',
};
