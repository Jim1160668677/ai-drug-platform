import { api } from './client';

// ========== 隐私计算 ==========

export const getPrivacyDomains = () => api.get('/privacy/domains').then((r) => r.data);

export const createPrivacyDomain = (payload: {
  name: string;
  data_schema?: Record<string, unknown>;
  privacy_params?: Record<string, unknown>;
}) => api.post('/privacy/domains', { name: payload.name, data_schema: payload.data_schema }).then((r) => r.data);
