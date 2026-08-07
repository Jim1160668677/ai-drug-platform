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
  enable_hypothesis?: boolean;
  hypothesis_config?: {
    use_llm?: boolean;
    mode?: string;
    max_hypotheses?: number;
  };
  /** 从指定步骤恢复（跳过之前的步骤） */
  resume_from_step?: 'target_discovery' | 'molecule_generation' | 'treatment_matching' | 'hypothesis_generation';
  /** 跳过指定步骤 */
  skip_steps?: string[];
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
    hypothesis_generation?: {
      status: string;
      hypotheses_generated: number;
      hypotheses_saved: number;
      mode: string;
      use_llm: boolean;
      duration_sec: number;
    };
  };
  summary: {
    total_targets: number;
    total_molecules: number;
    total_treatments: number;
    total_hypotheses?: number;
    custom_steps_executed?: number;
    skipped_steps?: string[];
    resumed_from?: string | null;
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

// 流水线是长耗时操作（实测最小参数 78s+，默认参数更久），
// 全局 60s timeout 会导致 net::ERR_ABORTED。这里单独放宽到 5 分钟。
export const runPipeline = (payload: PipelineRunRequest) =>
  api
    .post('/pipeline/run', payload, { timeout: 300000 })
    .then((r) => r.data);

export const getPipelineStatus = (projectId: string) =>
  api.get(`/pipeline/status/${projectId}`).then((r) => r.data);
