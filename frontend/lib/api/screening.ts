import { api } from './client';

// ========== 类型定义 ==========

export interface DualContextInput {
  smiles_list: string[];
  target_id?: string;
  target_pdb?: string;
  contexts?: string[];
}

export interface AmplifierEntry {
  smiles: string;
  score: number;
  mechanism?: string;
}

export interface DualContextResult {
  contexts: string[];
  results: Array<{
    smiles: string;
    efficacy_active: number;
    efficacy_neutral: number;
    conditional_amplification_score: number;
    is_amplifier: boolean;
  }>;
  amplifiers: AmplifierEntry[];
  summary: string;
  n_amplifiers: number;
  n_total: number;
  threshold: number;
  source: string;
  target_id?: string;
  target_gene?: string;
}

export interface VaccineDesignInput {
  project_id?: string;
  target_id: string;
  mutation_sequence: string;
  mhc_alleles?: string[];
}

export interface VaccineDesignResult {
  vaccine_sequence?: string;
  gc_content?: number;
  length?: number;
  immunogenicity_score?: number;
  notes?: string;
  cost_usd?: number;
  duration_sec?: number;
  steps_completed?: number;
}

// ========== API 调用 ==========

export const dualContextScreen = (data: DualContextInput) =>
  api.post('/screening/dual-context', data).then((r) => r.data?.data ?? r.data) as Promise<DualContextResult>;

export const designVaccine = (data: VaccineDesignInput) =>
  api.post('/screening/vaccine', data).then((r) => r.data?.data ?? r.data) as Promise<VaccineDesignResult>;
