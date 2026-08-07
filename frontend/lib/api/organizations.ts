import { api } from './client';

// ========== 机构与职能维度 ==========

export interface Organization {
  id: string;
  name: string;
  org_type: string;
  license_no?: string;
  contact_email?: string;
  address?: string;
  capabilities?: string[];
  metadata?: Record<string, unknown>;
  is_active: boolean;
  created_at?: string;
}

export interface FunctionMatrix {
  matrix: Record<string, string[]>;
  workspaces: Record<string, string>;
  default_permissions: Record<string, string[]>;
  function_roles: string[];
  org_types: string[];
}

export interface OrgUser {
  id: string;
  email: string;
  name: string;
  role: string;
  function_role?: string;
  title?: string;
  is_active: boolean;
}

export interface MyWorkspace {
  workspace: string;
  function_role?: string | null;
  org_id?: string | null;
}

export const listOrganizations = (
  params?: { org_type?: string; page?: number; page_size?: number }
) => api.get('/organizations', { params }).then((r) => r.data);

export const getOrganization = (id: string) =>
  api.get(`/organizations/${id}`).then((r) => r.data);

export const createOrganization = (payload: Partial<Organization>) =>
  api.post('/organizations', payload).then((r) => r.data);

export const updateOrganization = (id: string, payload: Partial<Organization>) =>
  api.patch(`/organizations/${id}`, payload).then((r) => r.data);

export const getFunctionMatrix = () =>
  api.get('/organizations/function-matrix').then((r) => r.data);

export const getMyWorkspace = () =>
  api.get('/organizations/me/workspace').then((r) => r.data);

export const listOrgUsers = (orgId: string) =>
  api.get(`/organizations/${orgId}/users`).then((r) => r.data);

export const assignUserToOrg = (
  orgId: string,
  payload: { user_id: string; function_role?: string; title?: string }
) => api.post(`/organizations/${orgId}/assign-user`, payload).then((r) => r.data);

// 机构类型中文标签
export const ORG_TYPE_LABELS: Record<string, string> = {
  research_institute: '科研院所',
  pharma: '药企',
  hospital: '医院',
  cro: 'CRO',
  cdmo: 'CDMO',
  testing_lab: '检测机构',
};

// 职能角色中文标签
export const FUNCTION_ROLE_LABELS: Record<string, string> = {
  target_discovery: '靶点发现',
  molecule_design: '分子设计',
  clinical_guidance: '用药指导',
  experiment_validation: '实验验证',
  project_pi: '项目PI',
  regulatory: '注册申报',
  data_engineering: '数据工程',
};
