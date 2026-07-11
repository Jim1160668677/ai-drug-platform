import { api } from './client';

// ========== 联邦学习 ==========

export const getFederatedJobs = () => api.get('/federated/jobs').then((r) => r.data);

export const createFederatedJob = (payload: {
  project_id: string;
  min_clients?: number;
  rounds?: number;
}) => api.post('/federated/jobs', payload).then((r) => r.data);

export const stopFederatedJob = (jobId: string) =>
  api.post(`/federated/jobs/${jobId}/stop`).then((r) => r.data);
