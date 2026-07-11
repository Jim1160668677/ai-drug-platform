import { api } from './client';

// ========== 治疗方案 ==========

export const getTreatments = (projectId?: string) =>
  api.get('/treatments', { params: { project_id: projectId } }).then((r) => r.data);

export const optimizeTreatments = (projectId: string) =>
  api.post('/treatments/optimize', null, { params: { project_id: projectId } }).then((r) => r.data);

export const monitorEfficacy = (id: string) => api.post(`/treatments/${id}/monitor`).then((r) => r.data);
