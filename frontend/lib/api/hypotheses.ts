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

export const getHypothesisDetail = (id: string) =>
  api.get(`/hypotheses/${id}`).then((r) => r.data);

export const deleteHypothesis = (id: string) =>
  api.delete(`/hypotheses/${id}`).then((r) => r.data);

export const eliminateHypothesis = (id: string, reason: string) =>
  api.post(`/hypotheses/${id}/eliminate`, { reason }).then((r) => r.data);

export const mergeHypothesis = (id: string, targetId: string) =>
  api.post(`/hypotheses/${id}/merge`, null, { params: { target_hypothesis_id: targetId } }).then((r) => r.data);

// ========== 自动生成假设 ==========

export const autoGenerateHypotheses = (
  projectId: string,
  maxHypotheses?: number,
  context?: Record<string, unknown>
) =>
  api
    .post('/hypotheses/auto-generate', {
      project_id: projectId,
      max_hypotheses: maxHypotheses,
      context,
    })
    .then((r) => r.data?.data ?? r.data);
