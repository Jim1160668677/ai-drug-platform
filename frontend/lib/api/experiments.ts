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
