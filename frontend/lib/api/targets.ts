import { api } from './client';

// ========== 靶点 ==========

export const discoverTargets = ({
  projectId,
  datasetId,
  tier,
}: {
  projectId: string;
  datasetId?: string;
  tier: string;
}) =>
  api
    .post('/targets/discover', null, {
      params: { project_id: projectId, dataset_id: datasetId, tier },
    })
    .then((r) => r.data);

export const getTargets = (projectId?: string, evidenceGrade?: string) =>
  api
    .get('/targets', { params: { project_id: projectId, evidence_grade: evidenceGrade } })
    .then((r) => r.data);

export const repurposeTarget = (id: string) => api.post(`/targets/${id}/repurpose`).then((r) => r.data);
export const buildEvidence = (id: string) => api.post(`/targets/${id}/evidence`).then((r) => r.data);
