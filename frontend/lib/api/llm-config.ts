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
