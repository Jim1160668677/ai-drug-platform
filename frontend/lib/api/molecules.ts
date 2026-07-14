import { api } from './client';

// ========== 分子 ==========

export const getMolecules = (targetId?: string) =>
  api.get('/molecules', { params: { target_id: targetId } }).then((r) => r.data);

export const designMolecule = (payload: Record<string, unknown>) =>
  api.post('/molecules/design', payload).then((r) => r.data);

export const assessDruglikeness = (smiles: string) =>
  api.post('/molecules/assess', null, { params: { smiles } }).then((r) => r.data);

export const deleteMolecule = (id: string) =>
  api.delete(`/molecules/${id}`).then((r) => r.data);

// ========== 分子新端点 ==========

export const predictProperties = (smiles: string) =>
  api.post('/molecules/predict-properties', { smiles }).then((r) => r.data);

export const explainMolecule = (smiles: string) =>
  api.post('/molecules/explain', { smiles }).then((r) => r.data);

// ========== 多靶点协同分子设计 ==========

export const designMultiTargetMolecules = (
  targets: Array<{ target_id: string; name?: string; binding_site?: string; weight?: number }>,
  seedSmiles?: string,
  constraints?: Record<string, unknown>,
  nMolecules?: number
) =>
  api
    .post('/molecules/design-multi-target', {
      targets,
      seed_smiles: seedSmiles,
      constraints,
      n_molecules: nMolecules,
    })
    .then((r) => r.data?.data ?? r.data);
