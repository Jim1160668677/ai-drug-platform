import { api } from './client';

// ========== 用户管理（admin） ==========

export const getUsers = (params?: { skip?: number; limit?: number; role?: string; is_active?: boolean }) =>
  api.get('/users', { params }).then((r) => r.data);

export const updateUserRole = (userId: string, role: string) =>
  api.patch(`/users/${userId}/role`, { role }).then((r) => r.data);

export const updateUserStatus = (userId: string, isActive: boolean) =>
  api.patch(`/users/${userId}/status`, { is_active: isActive }).then((r) => r.data);
