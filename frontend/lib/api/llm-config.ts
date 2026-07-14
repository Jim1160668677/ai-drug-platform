import { api } from './client';

// ========== LLM 配置管理 ==========

export const getLLMConfigs = () => api.get('/llm-configs').then((r) => r.data);

export const createLLMConfig = (payload: Record<string, unknown>) =>
  api.post('/llm-configs', payload).then((r) => r.data);

export const updateLLMConfig = (id: string, payload: Record<string, unknown>) =>
  api.put(`/llm-configs/${id}`, payload).then((r) => r.data);

export const deleteLLMConfig = (id: string) => api.delete(`/llm-configs/${id}`).then((r) => r.data);

export const activateLLMConfig = (id: string) =>
  api.post(`/llm-configs/${id}/activate`).then((r) => r.data);

export const testLLMConfig = (payload: { config_id?: string; custom_message?: string }) =>
  api.post('/llm-configs/test', payload).then((r) => r.data);

// ========== LLM 监控与缓存 ==========

export const getLLMMetrics = (days = 7) =>
  api.get('/llm-configs/metrics', { params: { days } }).then((r) => r.data?.data ?? r.data);

export const getCacheStats = () =>
  api.get('/llm-configs/cache/stats').then((r) => r.data?.data ?? r.data);

export const invalidateCache = () =>
  api.delete('/llm-configs/cache').then((r) => r.data?.data ?? r.data);
