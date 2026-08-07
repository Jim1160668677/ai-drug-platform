import { api } from './client';

// ========== 类型定义 ==========

export type BenchmarkMode = 'hybrid' | 'traditional_supercompute' | 'llm_only';

export interface BenchmarkMetrics {
  accuracy_score: number;
  cost_usd: number;
  duration_sec: number;
  energy_kwh: number;
  coverage_pct: number;
  novelty_score: number;
  interpretability_score: number;
}

export interface BenchmarkRunInput {
  case_id: string;
  mode: BenchmarkMode;
  smiles: string;
  target_pdb?: string;
  target_gene?: string;
}

export interface BenchmarkRunResult {
  case_id: string;
  mode: BenchmarkMode;
  metrics: BenchmarkMetrics;
  report_id: string;
  smiles: string;
}

export interface BenchmarkCompareResult {
  case_id: string;
  smiles: string;
  results: Record<BenchmarkMode, BenchmarkRunResult>;
  comparison: {
    cost_saving_pct: number;
    accuracy_change_pct: number;
    energy_saving_pct: number;
    speedup_factor: number;
  };
  winner: BenchmarkMode;
}

export interface BenchmarkAllResult {
  total_cases: number;
  completed: number;
  cases: Array<{
    case_id: string;
    comparison: BenchmarkCompareResult['comparison'];
    winner: BenchmarkMode;
  }>;
  summary: {
    avg_cost_saving_pct: number;
    avg_accuracy_change_pct: number;
    avg_speedup_factor: number;
    hybrid_wins: number;
    supercompute_wins: number;
    llm_only_wins: number;
  };
  conclusion: string;
}

export interface BenchmarkReport {
  id: string;
  case_id: string;
  mode: BenchmarkMode;
  metrics: BenchmarkMetrics;
  summary: string | null;
  input_smiles: string | null;
  input_target: string | null;
  cost_saving_pct: number | null;
  accuracy_change_pct: number | null;
  created_at: string | null;
}

// ========== API 调用 ==========

export const runBenchmark = (data: BenchmarkRunInput) =>
  api.post('/benchmarks/run', data).then((r) => r.data as BenchmarkRunResult);

export const compareBenchmarks = (data: {
  case_id: string;
  smiles: string;
  target_pdb?: string;
  target_gene?: string;
}) => api.post('/benchmarks/compare', data).then((r) => r.data as BenchmarkCompareResult);

export const runAllBenchmarks = () =>
  api.post('/benchmarks/run-all', {}).then((r) => r.data as BenchmarkAllResult);

export const listBenchmarks = (params: { page?: number; page_size?: number } = {}) =>
  api
    .get('/benchmarks', {
      params: { page: params.page ?? 1, page_size: params.page_size ?? 20 },
    })
    .then((r) => r.data);

export const getBenchmark = (id: string) =>
  api.get(`/benchmarks/${id}`).then((r) => r.data as BenchmarkReport);

// ========== 案例常量 ==========

export const BENCHMARK_CASES = [
  { case_id: 'aspirin', smiles: 'CC(=O)Oc1ccccc1C(=O)O', target_gene: 'PTGS2', label: '阿司匹林（易）' },
  { case_id: 'ibuprofen', smiles: 'CC(C)Cc1ccc(cc1)C(C)C(=O)O', target_gene: 'PTGS2', label: '布洛芬（易）' },
  { case_id: 'paracetamol', smiles: 'CC(=O)Nc1ccc(O)cc1', target_gene: 'PTGS2', label: '对乙酰氨基酚（易）' },
  { case_id: 'caffeine', smiles: 'CN1C=NC2=C1C(=O)N(C(=O)N2C)C', target_gene: 'ADORA2A', label: '咖啡因（中）' },
  { case_id: 'omeprazole', smiles: 'COc1ccc2[nH]c(nc2c1)S(=O)Cc1ncc(C)c(OC)c1C', target_gene: 'ATP4A', label: '奥美拉唑（难）' },
  { case_id: 'imatinib', smiles: 'Cc1ccc(NC(=O)c2cccnc2)cc1NC(=O)c2ccc(NC(=O)CSc3nnnn3C)c(c2)C', target_gene: 'ABL1', label: '伊马替尼（难）' },
  { case_id: 'gefitinib', smiles: 'Clc1ccc(Oc2cc3ncnc(Nc4ccc(NC(=O)NC)cc4C)c3cc2Cl)cc1', target_gene: 'EGFR', label: '吉非替尼（难）' },
  { case_id: 'osimertinib', smiles: 'COC1=C(NC(=O)C=C)C=C(NC2=NC=C3C=CNC3=N2)C=C1', target_gene: 'EGFR', label: '奥希替尼（难）' },
  { case_id: 'aspirin_variant', smiles: 'CC(=O)Oc1ccccc1C(=O)NC', target_gene: 'PTGS2', label: '阿司匹林变体（中）' },
] as const;
