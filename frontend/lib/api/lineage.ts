import { api } from './client';

// ========== 数据血缘 ==========

export interface LineageNode {
  type: string;
  id: string;
  depth: number;
  direction: 'upstream' | 'downstream' | 'center';
}

export interface LineageEdge {
  source: string;
  target: string;
  transformation: string;
  meta?: Record<string, any>;
}

export interface LineageDAG {
  nodes: LineageNode[];
  edges: LineageEdge[];
  node_count: number;
  edge_count: number;
}

export interface LineageItem {
  node_type: string;
  node_id: string;
  transformation: string;
  depth: number;
  meta?: Record<string, any>;
}

export const recordLineage = (data: {
  project_id: string;
  source_type: string;
  source_id: string;
  target_type: string;
  target_id: string;
  transformation: string;
  transformation_meta?: Record<string, any>;
}) => api.post('/lineage', data).then((r) => r.data?.data ?? r.data);

export const getUpstream = (projectId: string, nodeType: string, nodeId: string, depth = 3) =>
  api
    .get('/lineage/upstream', { params: { project_id: projectId, node_type: nodeType, node_id: nodeId, depth } })
    .then((r) => (r.data?.data ?? r.data) as LineageItem[]);

export const getDownstream = (projectId: string, nodeType: string, nodeId: string, depth = 3) =>
  api
    .get('/lineage/downstream', { params: { project_id: projectId, node_type: nodeType, node_id: nodeId, depth } })
    .then((r) => (r.data?.data ?? r.data) as LineageItem[]);

export const getDAG = (projectId: string, nodeType: string, nodeId: string, depth = 3) =>
  api
    .get('/lineage/dag', { params: { project_id: projectId, node_type: nodeType, node_id: nodeId, depth } })
    .then((r) => (r.data?.data ?? r.data) as LineageDAG);
