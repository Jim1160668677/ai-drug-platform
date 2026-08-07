import { api } from './client';

// ========== 类型定义 ==========

export interface PerturbationInput {
  gene: string;
  expression_matrix?: Record<string, unknown>;
  cell_type?: string;
}

export interface AnnotationInput {
  expression_matrix: Record<string, unknown>;
  n_clusters?: number;
}

export interface PerturbationResult {
  gene: string;
  predicted_effect: string;
  affected_pathways?: string[];
  confidence: number;
  source: string;
}

export interface AnnotationResult {
  cell_types: Array<{ cluster: number; cell_type: string; confidence: number }>;
  source: string;
}

export interface CellEngineInfo {
  name: string;
  available: boolean;
  mode: string;
}

// ========== API 调用 ==========

export const predictPerturbation = (data: PerturbationInput) =>
  api.post('/cells/perturbation', data).then((r) => r.data as PerturbationResult);

export const annotateCells = (data: AnnotationInput) =>
  api.post('/cells/annotate', data).then((r) => r.data as AnnotationResult);

export const listCellEngines = () =>
  api.get('/cells/engines').then((r) => r.data as CellEngineInfo[]);
