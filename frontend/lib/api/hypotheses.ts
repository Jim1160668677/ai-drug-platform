import { api } from './client';

// ========== 假设 ==========

export const getHypotheses = (projectId?: string) =>
  api.get('/hypotheses', { params: { project_id: projectId } }).then((r) => r.data);

export const createHypothesis = (payload: Record<string, unknown>, projectId: string) =>
  api.post('/hypotheses', payload, { params: { project_id: projectId } }).then((r) => r.data);

export const analyzeHypothesis = (id: string, tier: string = 'fast_screen') =>
  api.post(`/hypotheses/${id}/analyze`, null, { params: { tier } }).then((r) => r.data);

export const compareHypotheses = (projectId: string) =>
  api.get('/hypotheses/compare', { params: { project_id: projectId } }).then((r) => r.data);
