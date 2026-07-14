import { api } from './client';

// ========== 数据 ==========

export const getDatasets = (projectId?: string) =>
  api.get('/data', { params: { project_id: projectId } }).then((r) => r.data);

export const uploadData = ({
  projectId,
  name,
  dataType,
  source,
  file,
}: {
  projectId: string;
  name: string;
  dataType: string;
  source?: string;
  file: File;
}) => {
  const formData = new FormData();
  formData.append('file', file);
  return api
    .post('/data/upload', formData, {
      params: { project_id: projectId, name, data_type: dataType, source: source || '' },
      headers: { 'Content-Type': 'multipart/form-data' },
    })
    .then((r) => r.data);
};

export const parseDataset = (id: string) => api.post(`/data/${id}/parse`).then((r) => r.data);
export const getQuality = (id: string) => api.get(`/data/${id}/quality`).then((r) => r.data);
export const deleteDataset = (id: string) => api.delete(`/data/${id}`).then((r) => r.data);

// ========== 生信分析 ==========

export const analyzeDataset = (
  datasetId: string,
  analysisType: string,
  params?: Record<string, unknown>
) =>
  api
    .post(`/data/${datasetId}/analyze`, { analysis_type: analysisType, ...params })
    .then((r) => r.data?.data ?? r.data);

export const exportDataset = (datasetId: string, format: string, analysisType?: string) =>
  api
    .post(`/data/${datasetId}/export`, { format, analysis_type: analysisType })
    .then((r) => r.data?.data ?? r.data);

export const importDataFile = (projectId: string, name: string, file: File) => {
  const formData = new FormData();
  formData.append('file', file);
  return api
    .post(`/data/import`, formData, {
      params: { project_id: projectId, name },
      headers: { 'Content-Type': 'multipart/form-data' },
    })
    .then((r) => r.data?.data ?? r.data);
};

