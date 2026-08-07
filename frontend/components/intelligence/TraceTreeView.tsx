'use client';

/**
 * TraceTreeView — 推理步骤树可视化（组件 8/18）
 *
 * 使用 reactflow + dagre 渲染步骤树，节点高亮 status/cost。
 * 端点：GET /intelligence/runs/{id}/trace-tree
 */
import { useCallback } from 'react';
import ReactFlow, {
  Background,
  Controls,
  type Node,
  type Edge,
  type NodeProps,
  Handle,
  Position,
} from 'reactflow';
import dagre from 'dagre';
import { useQuery } from '@tanstack/react-query';
import { CheckCircle, XCircle, Loader2, DollarSign } from 'lucide-react';
import clsx from 'clsx';
import Card from '@/components/ui/Card';
import EmptyState from '@/components/ui/EmptyState';
import { getTraceTree } from '@/lib/api';
import type { TraceTreeNode } from '@/types/intelligence';
import 'reactflow/dist/style.css';

interface TraceTreeViewProps {
  runId: string;
  onStepClick?: (stepId: string) => void;
}

// 自定义节点
function StepNode({ data }: NodeProps) {
  const status = data.status || 'completed';
  const StatusIcon = status === 'completed' ? CheckCircle : status === 'failed' ? XCircle : Loader2;
  return (
    <div
      className={clsx(
        'px-3 py-2 rounded-lg border-2 bg-white shadow-sm min-w-[140px]',
        status === 'completed' ? 'border-green-300'
        : status === 'failed' ? 'border-red-300'
        : 'border-blue-300',
      )}
    >
      <Handle type="target" position={Position.Top} />
      <div className="flex items-center gap-1.5">
        <StatusIcon className={clsx('w-3.5 h-3.5', status === 'completed' ? 'text-green-500' : status === 'failed' ? 'text-red-500' : 'text-blue-500 animate-spin')} />
        <span className="text-xs font-medium text-gray-700">{data.label}</span>
      </div>
      {data.agent && <span className="text-xs text-purple-500 ml-5">@{data.agent}</span>}
      {data.cost != null && data.cost > 0 && (
        <span className="flex items-center gap-0.5 text-xs text-gray-400 ml-5">
          <DollarSign className="w-2.5 h-2.5" />${data.cost.toFixed(4)}
        </span>
      )}
      <Handle type="source" position={Position.Bottom} />
    </div>
  );
}

const nodeTypes = { step: StepNode };

// dagre 自动布局
function layoutTree(nodes: Node[], edges: Edge[]): { nodes: Node[]; edges: Edge[] } {
  const g = new dagre.graphlib.Graph();
  g.setDefaultEdgeLabel(() => ({}));
  g.setGraph({ rankdir: 'TB', nodesep: 40, ranksep: 60 });

  nodes.forEach((n) => g.setNode(n.id, { width: 160, height: 60 }));
  edges.forEach((e) => g.setEdge(e.source, e.target));

  dagre.layout(g);

  return {
    nodes: nodes.map((n) => {
      const pos = g.node(n.id);
      return { ...n, position: { x: pos.x - 80, y: pos.y - 30 } };
    }),
    edges,
  };
}

// 递归展平树为 nodes + edges
function flattenTree(roots: TraceTreeNode[]): { nodes: Node[]; edges: Edge[] } {
  const nodes: Node[] = [];
  const edges: Edge[] = [];

  function walk(node: TraceTreeNode) {
    nodes.push({
      id: node.step_id,
      type: 'step',
      position: { x: 0, y: 0 },
      data: {
        label: node.step_type.replace(/_/g, ' '),
        agent: node.agent_name,
        cost: node.cost_usd,
        status: node.status,
      },
    });
    if (node.children) {
      for (const child of node.children) {
        edges.push({ id: `${node.step_id}-${child.step_id}`, source: node.step_id, target: child.step_id });
        walk(child);
      }
    }
  }
  roots.forEach(walk);
  return { nodes, edges };
}

export default function TraceTreeView({ runId }: TraceTreeViewProps) {
  const { data, isLoading } = useQuery({
    queryKey: ['intelligence-trace-tree', runId],
    queryFn: () => getTraceTree(runId),
    enabled: !!runId,
  });

  if (isLoading) {
    return <Card title="步骤树"><div className="h-48 flex items-center justify-center text-gray-400 text-sm">加载中...</div></Card>;
  }

  if (!data || data.roots.length === 0) {
    return <Card title="步骤树"><EmptyState title="暂无步骤树数据" /></Card>;
  }

  const { nodes: rawNodes, edges } = flattenTree(data.roots);
  const { nodes } = layoutTree(rawNodes, edges);

  return (
    <Card title={`步骤树 (${data.total_steps} 步, $${data.total_cost.toFixed(4)})`}>
      <div style={{ height: 360 }}>
        <ReactFlow nodes={nodes} edges={edges} nodeTypes={nodeTypes} fitView>
          <Background />
          <Controls showInteractive={false} />
        </ReactFlow>
      </div>
    </Card>
  );
}
