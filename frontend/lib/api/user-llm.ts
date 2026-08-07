import { api } from './client';

// ========== 用户级 LLM 配置（BYO Key） ==========

export const listUserLlmConfigs = (page = 1, pageSize = 50) =>
  api
    .get('/users/me/llm-configs', { params: { page, page_size: pageSize } })
    .then((r) => r.data);

export const getActiveUserLlmConfig = () =>
  api.get('/users/me/llm-configs/active').then((r) => r.data);

export const createUserLlmConfig = (payload: Record<string, unknown>) =>
  api.post('/users/me/llm-configs', payload).then((r) => r.data);

export const updateUserLlmConfig = (id: string, payload: Record<string, unknown>) =>
  api.put(`/users/me/llm-configs/${id}`, payload).then((r) => r.data);

export const deleteUserLlmConfig = (id: string) =>
  api.delete(`/users/me/llm-configs/${id}`).then((r) => r.data);

export const activateUserLlmConfig = (id: string) =>
  api.post(`/users/me/llm-configs/${id}/activate`).then((r) => r.data);

export const testUserLlmConfig = (payload: {
  config_id?: string;
  custom_message?: string;
}) => api.post('/users/me/llm-configs/test', payload).then((r) => r.data);

// ========== 聚合导出 ==========

export const userLlmApi = {
  list: listUserLlmConfigs,
  getActive: getActiveUserLlmConfig,
  create: createUserLlmConfig,
  update: updateUserLlmConfig,
  delete: deleteUserLlmConfig,
  activate: activateUserLlmConfig,
  test: testUserLlmConfig,
};
