import { api } from './client';

// ========== 类型定义 ==========

export interface EfficacySummary {
  total_treatments: number;
  total_outcomes: number;
  orr: { orr: number; cr: number; pr: number; total: number };
  dcr: { dcr: number; cr: number; pr: number; sd: number; pd: number; total: number };
  overall_orr: number;
  overall_dcr: number;
  median_pfs_days: number | null;
  median_os_days: number | null;
  ae_distribution: Record<string, number>;
  by_target: Record<string, { count: number; orr: number; dcr: number; ae_count: number }>;
  records: EfficacyRecord[];
}

export interface EfficacyRecord {
  id: string;
  treatment_id: string;
  treatment_name: string | null;
  target_name: string | null;
  recist_response: string | null;
  follow_up_days: number | null;
  adverse_events: any[];
  created_at: string | null;
}

export interface RecordOutcomeInput {
  treatment_id: string;
  outcome: {
    /** RECIST 响应：CR / PR / SD / PD（可选，未提供时根据 lesions 自动分类） */
    response?: string;
    /** 病灶测量值 [{baseline_mm, current_mm}, ...] */
    lesions?: { baseline_mm: number; current_mm: number }[];
    /** 随访天数 */
    time?: number;
    /** 事件类型：1=死亡/进展, 0=删失 */
    event?: number;
  };
}

export interface RecordAdverseEventInput {
  treatment_id: string;
  event: {
    symptom: string;
    severity: string;
    description?: string;
  };
}

export interface RecistClassifyInput {
  lesions: { baseline_mm: number; current_mm: number }[];
}

export interface KaplanMeierInput {
  events: { time: number; event: number }[];
}

// ========== API 调用 ==========

/** 获取项目级疗效汇总（含 ORR/DCR/PFS/OS/记录列表/按靶点分组） */
export const getEfficacySummary = (projectId?: string) =>
  api
    .get('/efficacy/global-summary', { params: { project_id: projectId } })
    .then((r) => (r.data?.data ?? r.data) as EfficacySummary);

/** 旧接口保留兼容（实际调用 global-summary） */
export const getEfficacyRecords = (params?: { project_id?: string; limit?: number }) =>
  api
    .get('/efficacy/global-summary', { params: { project_id: params?.project_id } })
    .then((r) => {
      const summary = (r.data?.data ?? r.data) as EfficacySummary;
      return summary?.records ?? [];
    });

/** 记录疗效结局 */
export const recordOutcome = (data: RecordOutcomeInput) =>
  api
    .post('/efficacy/outcomes', data)
    .then((r) => (r.data?.data ?? r.data));

/** 记录不良事件（自动 CTCAE 分级） */
export const recordAdverseEvent = (data: RecordAdverseEventInput) =>
  api
    .post('/efficacy/adverse-events', data)
    .then((r) => (r.data?.data ?? r.data));

/** RECIST 1.1 响应分类 */
export const recistClassify = (data: RecistClassifyInput) =>
  api
    .post('/efficacy/recist-classify', data)
    .then((r) => (r.data?.data ?? r.data));

/** Kaplan-Meier 生存分析 */
export const kaplanMeier = (data: KaplanMeierInput) =>
  api
    .post('/efficacy/kaplan-meier', data)
    .then((r) => (r.data?.data ?? r.data));
