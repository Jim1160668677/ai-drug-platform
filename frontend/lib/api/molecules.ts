import { api } from './client';

// ========== 分子 ==========

export const getMolecules = (targetId?: string) =>
  api.get('/molecules', { params: { target_id: targetId } }).then((r) => r.data);

export const designMolecule = (payload: Record<string, unknown>) =>
  api.post('/molecules/design', payload).then((r) => r.data);

export const assessDruglikeness = (smiles: string) =>
  api.post('/molecules/assess', null, { params: { smiles } }).then((r) => r.data);

// ========== 分子新端点 ==========

export const predictProperties = (smiles: string) =>
  api.post('/molecules/predict-properties', { smiles }).then((r) => r.data);

export const explainMolecule = (smiles: string) =>
  api.post('/molecules/explain', { smiles }).then((r) => r.data);
