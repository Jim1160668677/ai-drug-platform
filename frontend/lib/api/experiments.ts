import { api } from './client';

// ========== 实验 ==========

export const getExperiments = (projectId?: string) =>
  api.get('/experiments', { params: { project_id: projectId } }).then((r) => r.data);

export const submitExperimentResult = (
  id: string,
  result: Record<string, unknown>,
  success: boolean,
  notes?: string
) => api.post(`/experiments/${id}/result`, { result, success, notes }).then((r) => r.data);

// ========== 实验调度 ==========

export interface ScheduleExperimentPayload {
  dsl: Record<string, unknown>;
  project_id: string;
  hypothesis_ids?: string[];
}

export interface ScheduleExperimentResponse {
  schedule_id: string;
  steps: Array<{ name: string; description: string; status: string }>;
  conflicts: Array<{ type: string; resource: string; details: string }>;
  nextflow_params?: Record<string, unknown>;
  lims_csv?: string;
  audit_log_id: string;
}

/** POST /experiments/schedule — 从 DSL 调度实验 */
export const scheduleExperiment = (
  payload: ScheduleExperimentPayload,
): Promise<ScheduleExperimentResponse> =>
  api.post('/experiments/schedule', payload).then((r) => r.data);
