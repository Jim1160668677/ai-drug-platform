import { api } from './client';

// ========== 类型定义 ==========

export interface ProteinStructure {
  id: string;
  target_id: string | null;
  sequence: string;
  plddt_mean: number;
  prediction_source: string;
  model_name: string;
  status: string;
  storage_path: string;
  created_at: string | null;
}

/** 结构预测引擎选择 */
export type StructureEngine = 'esmfold' | 'protenix';

export interface PredictStructureInput {
  sequence: string;
  target_id?: string;
  /** 配体 SMILES — 传入后自动切换到 Protenix 预测复合物结构 */
  ligand_smiles?: string;
  /** 显式指定引擎 */
  engine?: StructureEngine;
}

export interface PredictStructureResult {
  pdb_text?: string;
  plddt_mean: number;
  source: string;
  structure_id?: string;
  model_name?: string;
  storage_path?: string;
  sequence_length?: number;
  duration_sec?: number;
  /** 配体原子坐标（仅 Protenix 复合物预测返回） */
  ligand_coordinates?: [number, number, number][];
  /** 结合位点残基序号（仅 Protenix 复合物预测返回） */
  binding_site_residues?: number[];
  /** 每残基置信度（仅 Protenix 真实模式返回） */
  confidence_per_residue?: number[];
  error?: string;
}

export interface ListStructuresParams {
  target_id?: string;
  page?: number;
  page_size?: number;
}

// ========== API 调用 ==========

/**
 * 预测蛋白结构 — 自动选择引擎
 *
 * - 不传 ligand_smiles：ESMFold 仅预测蛋白结构
 * - 传 ligand_smiles：自动切换 Protenix 预测蛋白-配体复合物结构（含结合位点）
 */
export const predictStructure = (data: PredictStructureInput) =>
  api
    .post('/structures/predict', data)
    .then((r) => (r.data?.data ?? r.data) as PredictStructureResult);

/** 显式调用 Protenix 预测蛋白-配体复合物结构（必须传 ligand_smiles） */
export const predictComplex = (
  data: { sequence: string; ligand_smiles: string; target_id?: string }
) =>
  api
    .post('/structures/predict-complex', data)
    .then((r) => (r.data?.data ?? r.data) as PredictStructureResult);

export const getStructure = (id: string) =>
  api.get(`/structures/${id}`).then((r) => r.data as ProteinStructure);

export const listStructures = (params: ListStructuresParams = {}) =>
  api
    .get('/structures', {
      params: {
        target_id: params.target_id,
        page: params.page ?? 1,
        page_size: params.page_size ?? 20,
      },
    })
    .then((r) => r.data);
