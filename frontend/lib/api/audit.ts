import { api } from './client';

// ========== 审计 ==========

export const getAuditLogs = (limit: number = 50) =>
  api.get('/audit/logs', { params: { limit } }).then((r) => r.data);
