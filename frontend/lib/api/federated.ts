import { api } from './client';

// ========== 联邦学习 ==========

export const getFederatedJobs = (status?: string) =>
  api.get('/federated/jobs', { params: status ? { status } : undefined }).then((r) => r.data);

export const createFederatedJob = (payload: {
  project_id: string;
  min_clients?: number;
  num_rounds?: number;
}) => api.post('/federated/jobs', payload).then((r) => r.data);

export const stopFederatedJob = (jobId: string) =>
  api.post(`/federated/jobs/${jobId}/stop`).then((r) => r.data);

export const getFederatedJobDetail = (jobId: string) =>
  api.get(`/federated/jobs/${jobId}`).then((r) => r.data);
