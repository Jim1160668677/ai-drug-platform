// 前端 API 库统一入口
// 按功能领域拆分模块，统一从此处导出，调用方使用 `import { xxx } from '@/lib/api'`
//
// 已移除的重复函数：
// - assessDruglikenessV2（未使用，与 assessDruglikeness 功能重复）
// - getDatasetsV2（未使用，与 getDatasets 功能重复）

export { api, default } from './client';

export * from './auth';
export * from './projects';
export * from './datasets';
export * from './targets';
export * from './molecules';
export * from './treatments';
export * from './experiments';
export * from './chat';
export * from './hypotheses';
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

export type { ApiResponse, PagedResponse, ErrorResponse, StandardResponse } from './types';
