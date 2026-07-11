import { api } from './client';

// ========== 全局看板 ==========

export const getDashboardOverview = () => api.get('/dashboard/overview').then((r) => r.data);
