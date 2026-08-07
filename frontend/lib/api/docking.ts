import { api } from './client';

// ========== 类型定义 ==========

export type DockingMode = 'hybrid' | 'unimol' | 'vina';

export interface UniMolDockInput {
  smiles: string;
  target_pdb?: string;
  target_name?: string;
}

export interface VinaDockInput {
  smiles: string;
  receptor_pdbqt?: string;
  box?: { center?: number[]; size?: number[] };
  exhaustiveness?: number;
  num_poses?: number;
}

export interface HybridDockInput {
  project_id?: string;
  target_id: string;
  smiles_list: string[];
  top_k?: number;
}

export interface BindingPose {
  mol_block?: string;
  coordinates?: number[][];
  box_center?: number[];
  box_size?: number[];
  rmsd?: number;
  target_name?: string;
  n_poses?: number;
  exhaustiveness?: number;
  atom_count?: number;
  heavy_atom_count?: number;
  lipinski_pass?: boolean;
}

export interface DockingResult {
  smiles?: string;
  affinity?: number;
  rmsd?: number;
  confidence?: number;
  source?: string;
  ki?: number;
  ligand_efficiency?: number;
  binding_pose?: BindingPose;
  pose?: BindingPose;
}

export interface HybridDockResult {
  final_ranking: Array<{
    smiles: string;
    final_score: number;
    reason?: string;
  }>;
  docking_results: DockingResult[];
  report: string;
  cost_usd: number;
  duration_sec: number;
  energy_kwh: number;
  steps_completed: number;
  truncated: boolean;
}

export interface ComputeJob {
  id: string;
  job_type: string;
  engine: string;
  mode: string;
  status: string;
  cost_usd: number | null;
  duration_sec: number | null;
  energy_kwh: number | null;
  created_at: string | null;
}

// ========== API 调用 ==========

// Hybrid 是 5 步 LLM 流程（LLM 假设 → Uni-Mol 粗筛 → LLM 重排 → Vina 精修 → LLM 报告），
// 单次 LLM 调用 5-30s，3 次调用 + N 次对接 = 必然超过默认 60s。
// 这里单独设置 300s（5 分钟）超时，避免 hybrid 接口因前端 axios 超时报错。
// 后端已优化：单分子并发 + 单 LLM 调用 45s 超时保护，整体正常应在 30-90s 完成。
const HYBRID_DOCK_TIMEOUT = 300_000;  // 5 分钟

export const unimolDock = (data: UniMolDockInput) =>
  api.post('/docking/unimol', data).then((r) => r.data as DockingResult);

export const vinaDock = (data: VinaDockInput) =>
  api.post('/docking/vina', data).then((r) => r.data as DockingResult);

export const hybridDock = (data: HybridDockInput) =>
  api
    .post('/docking/hybrid', data, { timeout: HYBRID_DOCK_TIMEOUT })
    .then((r) => r.data as HybridDockResult);

export const listDockingJobs = (params: { page?: number; page_size?: number } = {}) =>
  api
    .get('/docking/jobs', {
      params: { page: params.page ?? 1, page_size: params.page_size ?? 20 },
    })
    .then((r) => r.data);

export const getDockingJob = (id: string) =>
  api.get(`/docking/jobs/${id}`).then((r) => r.data as ComputeJob);
