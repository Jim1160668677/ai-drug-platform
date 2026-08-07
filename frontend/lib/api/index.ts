// 前端 API 库统一入口
// 按功能领域拆分模块，统一从此处导出，调用方使用 `import { xxx } from '@/lib/api'`

export { api, default } from './client';

export * from './auth';
export * from './projects';
export * from './datasets';
export * from './targets';
export * from './molecules';
export * from './treatments';
export * from './experiments';
export * from './chat';
export * from './reports';
export * from './audit';
export * from './users';
export * from './dashboard';
export * from './llm-config';
export * from './federated';
export * from './privacy';
export * from './efficacy';
export * from './pipeline';
export * from './ws';
export * from './lineage';
export * from './consent';
export * from './genome';
export * from './user-llm';
export * from './organizations';
export * from './developability';
export * from './translations';
export * from './validations';
export * from './structures';
export * from './docking';
export * from './cells';
export * from './screening';
export * from './benchmarks';
export * from './synthesis';

// hypotheses 模块先导出，coscientist 的同名导出使用别名
export * from './hypotheses';

// Agent 模块先导出，intelligence 的同名导出使用别名
export * from './agent';

// Coscientist 模块（避免与 hypotheses 冲突）
export {
  createRun,
  listRuns,
  getRun,
  cancelRun,
  deleteRun,
  getHypotheses as getCoScientistHypotheses,
  getHypothesisDetail as getCoScientistHypothesisDetail,
  getRankings,
  getDebates,
  getEvolutionTree,
  getProgress,
  getAgentStats,
  getMetaReview,
  submitFeedback,
  getCases,
  generateResearchGoal,
  getComprehensiveTemplate,
  listInsights,
  getPendingInsightCount,
  getInsight,
  acceptInsight,
  dismissInsight,
  markInsightRead,
  bulkMarkInsightsRead,
  quickReason,
  getSuggestedGoal,
  promoteHypothesisToTarget,
  promoteHypothesisToMolecule,
  promoteHypothesisToExperiment,
  promoteHypothesisToTreatment,
  type Insight,
} from './coscientist';

// 统一智能系统（避免与 agent 冲突）
export {
  createSession as createIntelligenceSession,
  listSessions as listIntelligenceSessions,
  getSession as getIntelligenceSession,
  archiveSession as archiveIntelligenceSession,
  sendChat as sendIntelligenceChat,
  forceMode,
  streamChat,
  getContext,
  getTrace,
  getTraceTree,
  getCostBreakdown,
  getDecisionChain,
  collectEvidence,
  collectEntityContext,
  interpretAnalysis,
  interpretDataset,
  normalizeMultimodal,
  analyzeVision,
  listRules,
  getRulePreset,
  executeRules,
  validateRules,
  type StreamCallbacks,
} from './intelligence';

export type { ApiResponse, PagedResponse, ErrorResponse, StandardResponse } from './types';