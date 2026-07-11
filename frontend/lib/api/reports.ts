import { api } from './client';

// ========== 报告 ==========

export const exportSDTM = (projectId: string) =>
  api.post(`/reports/${projectId}/sdtm`).then((r) => r.data);

export const exportADaM = (projectId: string) =>
  api.post(`/reports/${projectId}/adam`).then((r) => r.data);

export const getProjectSummary = (projectId: string) =>
  api.get(`/reports/${projectId}/summary`).then((r) => r.data);
