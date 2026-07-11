import { api } from './client';

// ========== 项目 ==========

export const getProjects = () => api.get('/projects').then((r) => r.data);
export const createProject = (payload: Record<string, unknown>) =>
  api.post('/projects', payload).then((r) => r.data);
