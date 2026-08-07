import { api } from './client';

// ========== 性状管理 ==========

export const listTraits = (category?: string, page = 1, pageSize = 20) =>
  api
    .get('/genome/traits', {
      params: { category, page, page_size: pageSize },
    })
    .then((r) => r.data);

export const getTrait = (id: string) =>
  api.get(`/genome/traits/${id}`).then((r) => r.data);

export const createTrait = (payload: Record<string, unknown>) =>
  api.post('/genome/traits', payload).then((r) => r.data);

export const getTraitLoci = (id: string, approvedOnly = true) =>
  api
    .get(`/genome/traits/${id}/loci`, { params: { approved_only: approvedOnly } })
    .then((r) => r.data);

export const searchLoci = (
  traitId: string,
  opts: { useExternal?: boolean; userLlmConfigId?: string } = {}
) =>
  api
    .post(`/genome/traits/${traitId}/search-loci`, null, {
      params: {
        use_external: opts.useExternal ?? true,
        user_llm_config_id: opts.userLlmConfigId,
      },
    })
    .then((r) => r.data);

// ========== 个人基因组文件 ==========

export const uploadGenome = (
  file: File,
  opts: { genomeBuild?: string; projectId?: string } = {}
) => {
  const formData = new FormData();
  formData.append('file', file);
  if (opts.genomeBuild) formData.append('genome_build', opts.genomeBuild);
  if (opts.projectId) formData.append('project_id', opts.projectId);
  return api
    .post('/genome/upload', formData, {
      headers: { 'Content-Type': 'multipart/form-data' },
    })
    .then((r) => r.data);
};

export const listGenomes = (page = 1, pageSize = 20) =>
  api
    .get('/genome/genomes', { params: { page, page_size: pageSize } })
    .then((r) => r.data);

export const getGenome = (id: string) =>
  api.get(`/genome/genomes/${id}`).then((r) => r.data);

export const deleteGenome = (id: string) =>
  api.delete(`/genome/genomes/${id}`).then((r) => r.data);

// ========== 基因型匹配 & 风险评分 ==========

export const matchGenotype = (genomeId: string, traitId: string) =>
  api
    .post(`/genome/genomes/${genomeId}/match`, null, {
      params: { trait_id: traitId },
    })
    .then((r) => r.data);

export const listMatches = (genomeId: string, riskOnly = false) =>
  api
    .get(`/genome/genomes/${genomeId}/matches`, { params: { risk_only: riskOnly } })
    .then((r) => r.data);

export const scoreRisk = (genomeId: string, traitId: string) =>
  api.post(`/genome/genomes/${genomeId}/risk/${traitId}`).then((r) => r.data);

export const listAssessments = (genomeId: string) =>
  api.get(`/genome/genomes/${genomeId}/assessments`).then((r) => r.data);

// ========== LLM 解读 & 生活建议 ==========

export const interpret = (
  assessmentId: string,
  payload: { use_llm?: boolean; user_llm_config_id?: string } = {}
) =>
  api
    .post(`/genome/assessments/${assessmentId}/interpret`, payload)
    .then((r) => r.data);

export const generateRecommendations = (assessmentId: string) =>
  api
    .post(`/genome/assessments/${assessmentId}/recommendations`)
    .then((r) => r.data);

export const listRecommendations = (assessmentId: string) =>
  api
    .get(`/genome/assessments/${assessmentId}/recommendations`)
    .then((r) => r.data);

// ========== 知识库扩充 ==========

export const expandKb = (payload: {
  trait_ids?: string[];
  user_llm_config_id?: string;
}) => api.post('/genome/kb/expand', payload).then((r) => r.data);

// ========== Prompt 模板 ==========

export const listPromptTemplates = (
  params: {
    templateType?: string;
    traitCategory?: string;
    page?: number;
    pageSize?: number;
  } = {}
) =>
  api
    .get('/genome/prompt-templates', {
      params: {
        template_type: params.templateType,
        trait_category: params.traitCategory,
        page: params.page ?? 1,
        page_size: params.pageSize ?? 50,
      },
    })
    .then((r) => r.data);

export const createPromptTemplate = (payload: Record<string, unknown>) =>
  api.post('/genome/prompt-templates', payload).then((r) => r.data);

// ========== 个性化治疗推荐 ==========

export const personalizedTreatment = (payload: {
  personal_genome_id: string;
  project_id?: string;
  disease?: string;
  user_llm_config_id?: string;
}) => api.post('/genome/personalized-treatment', payload).then((r) => r.data);

// ========== 知识图谱同步 ==========

export const syncGenomeToGraph = (genomeId: string) =>
  api.post(`/genome/genomes/${genomeId}/graph-sync`).then((r) => r.data);

// ========== 聚合导出（便于统一引用） ==========

export const genomeApi = {
  listTraits,
  getTrait,
  createTrait,
  getTraitLoci,
  searchLoci,
  uploadGenome,
  listGenomes,
  getGenome,
  deleteGenome,
  matchGenotype,
  listMatches,
  scoreRisk,
  listAssessments,
  interpret,
  generateRecommendations,
  listRecommendations,
  expandKb,
  listPromptTemplates,
  createPromptTemplate,
  personalizedTreatment,
  syncGenomeToGraph,
};
