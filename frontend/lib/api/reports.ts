import { api } from './client';

// ========== 报告 ==========

export const exportSDTM = (projectId: string) =>
  api.post(`/reports/${projectId}/sdtm`).then((r) => r.data);

export const exportADaM = (projectId: string) =>
  api.post(`/reports/${projectId}/adam`).then((r) => r.data);

export const getProjectSummary = (projectId: string) =>
  api.get(`/reports/${projectId}/summary`).then((r) => r.data);

// ========== FHIR R4 导出 ==========

export const exportFHIR = (projectId: string) =>
  api.post(`/reports/${projectId}/fhir`).then((r) => r.data?.data ?? r.data);

// ========== SDTM 校验 ==========

export const validateSDTM = (projectId: string) =>
  api.post(`/reports/${projectId}/sdtm/validate`).then((r) => r.data?.data ?? r.data);
