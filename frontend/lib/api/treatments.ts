import { api } from './client';

// ========== 治疗方案 ==========

export const getTreatments = (projectId?: string) =>
  api.get('/treatments', { params: { project_id: projectId } }).then((r) => r.data);

export const getTreatmentDetail = (id: string) =>
  api.get(`/treatments/${id}`).then((r) => r.data);

export const optimizeTreatments = (projectId: string) =>
  api.post('/treatments/optimize', null, { params: { project_id: projectId } }).then((r) => r.data);

export const monitorEfficacy = (id: string) => api.post(`/treatments/${id}/monitor`).then((r) => r.data);

export const deleteTreatment = (id: string) =>
  api.delete(`/treatments/${id}`).then((r) => r.data);

// ========== 药物相互作用（DDI）检查 ==========

export interface DDIResult {
  interactions: Array<{
    drug_a: string;
    drug_b: string;
    severity: string;
    mechanism: string;
    clinical_effect: string;
    source: string;
  }>;
  risk_level: 'none' | 'minor' | 'moderate' | 'major' | 'contraindicated';
  summary: string;
  drug_count: number;
}

export const checkDDI = (drugList: string[], targetList?: string[]) =>
  api
    .post('/treatments/ddi-check', {
      drug_list: drugList,
      target_list: targetList || null,
    })
    .then((r) => (r.data?.data ?? r.data) as DDIResult);

// ========== 临床反馈（干湿闭环） ==========

export const createClinicalFeedback = (treatmentId: string, feedbackData: Record<string, unknown>) =>
  api.post(`/treatments/${treatmentId}/clinical-feedback`, feedbackData).then((r) => r.data?.data ?? r.data);

export const getClinicalFeedbacks = (treatmentId: string) =>
  api.get(`/treatments/${treatmentId}/clinical-feedbacks`).then((r) => r.data?.data ?? r.data);
