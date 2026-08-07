import { api } from './client';

// ========== 合作方 ==========

export interface Partner {
  id: string;
  name: string;
  partner_type: 'cro' | 'cdmo' | 'hospital' | 'testing_lab' | 'registry';
  org_id: string | null;
  capabilities: string[];
  contact_name: string | null;
  contact_email: string | null;
  contact_phone: string | null;
  lead_time_days: number | null;
  cost_per_unit_usd: number | null;
  quality_rating: number | null;
  is_active: boolean;
  notes: string | null;
  created_at: string;
}

export const listPartners = (partnerType?: string, page = 1, pageSize = 20) =>
  api
    .get('/translations/partners', {
      params: { partner_type: partnerType, page, page_size: pageSize },
    })
    .then((r) => r.data);

export const getPartner = (id: string) =>
  api.get(`/translations/partners/${id}`).then((r) => r.data as Partner);

export const createPartner = (data: Partial<Partner>) =>
  api.post('/translations/partners', data).then((r) => r.data as Partner);

export const updatePartner = (id: string, data: Partial<Partner>) =>
  api.patch(`/translations/partners/${id}`, data).then((r) => r.data as Partner);

// ========== 转化阶段 ==========

export type StageStatus = 'not_started' | 'in_progress' | 'completed' | 'blocked';

export interface TranslationStage {
  id: string;
  project_id: string;
  molecule_id: string | null;
  stage_type: string;
  stage_name: string;
  description: string | null;
  status: StageStatus;
  partner_id: string | null;
  partner_name: string | null;
  start_date: string | null;
  estimated_end_date: string | null;
  actual_end_date: string | null;
  cost_usd: number | null;
  duration_days: number | null;
  exit_criteria: string[];
  exit_criteria_met: boolean;
  findings: string | null;
  go_no_go: string | null;
  order_index: number;
}

export interface Timeline {
  project_id: string;
  stages: TranslationStage[];
  total_cost_usd: number;
  total_duration_days: number;
  completion_pct: number;
  total_stages: number;
  completed_stages: number;
}

export const listStages = (projectId: string, moleculeId?: string) =>
  api
    .get(`/translations/projects/${projectId}/stages`, {
      params: { molecule_id: moleculeId },
    })
    .then((r) => r.data as TranslationStage[]);

export const createStage = (projectId: string, data: Partial<TranslationStage>) =>
  api
    .post(`/translations/projects/${projectId}/stages`, data)
    .then((r) => r.data as TranslationStage);

export const updateStage = (stageId: string, data: Partial<TranslationStage>) =>
  api.patch(`/translations/stages/${stageId}`, data).then((r) => r.data as TranslationStage);

export const getTimeline = (projectId: string) =>
  api.get(`/translations/projects/${projectId}/timeline`).then((r) => r.data as Timeline);

export const assignPartner = (stageId: string, partnerId: string) =>
  api
    .post(`/translations/stages/${stageId}/assign-partner`, { partner_id: partnerId })
    .then((r) => r.data as TranslationStage);

// ========== 常量标签 ==========

export const PARTNER_TYPE_LABELS: Record<string, string> = {
  cro: 'CRO（合同研究）',
  cdmo: 'CDMO（开发生产）',
  hospital: '临床医院',
  testing_lab: '检测机构',
  registry: '登记机构',
};

export const STAGE_TYPE_LABELS: Record<string, string> = {
  target_validation: '靶点验证',
  preclinical_adme: '临床前 ADME',
  preclinical_tox: '临床前毒理',
  ind_filing: 'IND 申请',
  phase1: 'I 期临床',
  phase2: 'II 期临床',
  phase3: 'III 期临床',
  nda_filing: 'NDA 申请',
};

export const STAGE_STATUS_LABELS: Record<string, string> = {
  not_started: '未开始',
  in_progress: '进行中',
  completed: '已完成',
  blocked: '阻塞',
};

export const STAGE_STATUS_COLORS: Record<string, string> = {
  not_started: 'bg-slate-100 text-slate-600 border-slate-300',
  in_progress: 'bg-blue-100 text-blue-700 border-blue-300',
  completed: 'bg-green-100 text-green-700 border-green-300',
  blocked: 'bg-red-100 text-red-700 border-red-300',
};
