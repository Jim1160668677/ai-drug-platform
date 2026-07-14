import { api } from './client';

// ========== 端到端流水线 ==========

export interface PipelineRunRequest {
  project_id: string;
  dataset_id?: string;
  tier?: string;
  max_targets?: number;
  molecules_per_target?: number;
  molecule_strategy?: string;
  skip_existing?: boolean;
}

export interface PipelineRunResult {
  project_id: string;
  duration_sec: number;
  steps: {
    target_discovery?: {
      status: string;
      targets_found: number;
      tier: string;
      duration_sec: number;
      error: string | null;
    };
    molecule_generation?: {
      status: string;
      targets_processed: number;
      molecules_generated: number;
      molecules_saved: number;
      errors: string[];
      duration_sec: number;
    };
    treatment_matching?: {
      status: string;
      treatments_created: number;
      errors: string[];
      duration_sec: number;
    };
  };
  summary: {
    total_targets: number;
    total_molecules: number;
    total_treatments: number;
  };
}

export interface PipelineStatus {
  project_id: string;
  datasets: number;
  targets: number;
  molecules: number;
  treatments: number;
  pipeline_ready: boolean;
  pipeline_complete: boolean;
}

export const runPipeline = (payload: PipelineRunRequest) =>
  api.post('/pipeline/run', payload).then((r) => r.data);

export const getPipelineStatus = (projectId: string) =>
  api.get(`/pipeline/status/${projectId}`).then((r) => r.data);
