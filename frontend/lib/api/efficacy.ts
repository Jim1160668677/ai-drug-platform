import { api } from './client';

// ========== 疗效监测 ==========

export const getEfficacySummary = (projectId?: string) =>
  api.get('/efficacy/summary', { params: { project_id: projectId } }).then((r) => r.data);

export const getEfficacyRecords = (params?: { project_id?: string; limit?: number }) =>
  api.get('/efficacy/records', { params }).then((r) => r.data);
