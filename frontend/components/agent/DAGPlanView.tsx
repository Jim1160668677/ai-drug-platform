'use client';

import { useMemo, useCallback } from 'react';
import ReactFlow, {
  Background,
  Controls,
  type Node,
  type Edge,
  type NodeProps,
  Handle,
  Position,
  BackgroundVariant,
} from 'reactflow';
import dagre from 'dagre';
import clsx from 'clsx';
import { Wrench, CheckCircle2, Loader2, Circle } from 'lucide-react';
import type { Plan, PlanStep } from '@/types/agent';
import 'reactflow/dist/style.css';

interface DAGPlanViewProps {
  /** 任务规划（来自 WS plan 事件或 task.plan） */
  plan: Plan | null;
  /** 当前执行步数（用于高亮） */
  currentStep?: number;
  /** 已完成的步数集合 */
  completedSteps?: Set<number>;
  /** 节点点击回调 */
  onStepClick?: (stepId: string) => void;
  /** 布局方向，默认 TB（top-bottom） */
  direction?: 'TB' | 'LR';
}

// ========== dagre 自动布局 ==========
const NODE_WIDTH = 180;
const NODE_HEIGHT = 56;

function layoutWithDagre(
  steps: PlanStep[],
  direction: 'TB' | 'LR' = 'TB'
): { nodes: Node[]; edges: Edge[] } {
  const g = new dagre.graphlib.Graph();
  g.setGraph({ rankdir: direction, nodesep: 40, ranksep: 60, marginx: 20, marginy: 20 });
  g.setDefaultEdgeLabel(() => ({}));

  // 添加节点
  for (const step of steps) {
    g.setNode(step.id, { width: NODE_WIDTH, height: NODE_HEIGHT });
  }

  // 添加边（depends_on → step.id）
  for (const step of steps) {
    for (const dep of step.depends_on) {
      if (steps.some((s) => s.id === dep)) {
        g.setEdge(dep, step.id);
      }
    }
  }

  dagre.layout(g);

  const nodes: Node[] = steps.map((step, idx) => {
    const node = g.node(step.id);
    return {
      id: step.id,
      type: 'planStep',
      position: { x: node.x - NODE_WIDTH / 2, y: node.y - NODE_HEIGHT / 2 },
      data: { step, stepIndex: idx + 1 },
    };
  });

  const edges: Edge[] = [];
  for (const step of steps) {
    for (const dep of step.depends_on) {
      if (steps.some((s) => s.id === dep)) {
        edges.push({
          id: `${dep}->${step.id}`,
          source: dep,
          target: step.id,
          type: 'smoothstep',
          animated: true,
          style: { stroke: '#94a3b8', strokeWidth: 1.5 },
        });
      }
    }
  }

  return { nodes, edges };
}

// ========== 自定义节点 ==========
function PlanStepNode({ data, selected }: NodeProps) {
  const { step, stepIndex } = data as { step: PlanStep; stepIndex: number };
  // 节点状态由外层通过 data 传入（currentStep/completedSteps）
  const isCurrent = (data as { isCurrent?: boolean }).isCurrent;
  const isCompleted = (data as { isCompleted?: boolean }).isCompleted;

  return (
    <div
      className={clsx(
        'flex flex-col justify-center px-3 rounded-md border-2 bg-white shadow-sm transition-all',
        isCurrent && 'border-blue-500 ring-2 ring-blue-200',
        isCompleted && 'border-green-400 bg-green-50',
        !isCurrent && !isCompleted && 'border-gray-200',
        selected && 'ring-2 ring-primary-300'
      )}
      style={{ width: NODE_WIDTH, minHeight: NODE_HEIGHT }}
    >
      <Handle type="target" position={Position.Top} className="!bg-gray-400 !w-2 !h-2" />
      <div className="flex items-center gap-1.5">
        {isCurrent && <Loader2 className="w-3.5 h-3.5 text-blue-500 animate-spin shrink-0" />}
        {isCompleted && <CheckCircle2 className="w-3.5 h-3.5 text-green-500 shrink-0" />}
        {!isCurrent && !isCompleted && <Circle className="w-3.5 h-3.5 text-gray-300 shrink-0" />}
        <Wrench className="w-3 h-3 text-gray-500 shrink-0" />
        <span className="text-xs font-mono font-medium text-gray-800 truncate">
          {step.tool}
        </span>
      </div>
      {step.description && (
        <div className="text-[10px] text-gray-500 truncate mt-0.5">
          {step.description}
        </div>
      )}
      <div className="text-[9px] text-gray-400 mt-0.5">#{stepIndex}</div>
      <Handle type="source" position={Position.Bottom} className="!bg-gray-400 !w-2 !h-2" />
    </div>
  );
}

const nodeTypes = { planStep: PlanStepNode };

// ========== 主组件 ==========
export function DAGPlanView({
  plan,
  currentStep,
  completedSteps,
  onStepClick,
  direction = 'TB',
}: DAGPlanViewProps) {
  const { nodes, edges } = useMemo(() => {
    if (!plan || !plan.steps || plan.steps.length === 0) {
      return { nodes: [], edges: [] };
    }
    const laid = layoutWithDagre(plan.steps, direction);

    // 标注节点状态（当前/已完成）
    laid.nodes = laid.nodes.map((n) => {
      const stepIndex = (n.data as { stepIndex: number }).stepIndex;
      return {
        ...n,
        data: {
          ...n.data,
          isCurrent: stepIndex === currentStep,
          isCompleted: completedSteps ? completedSteps.has(stepIndex) : false,
        },
      };
    });
    return laid;
  }, [plan, currentStep, completedSteps, direction]);

  const handleNodeClick = useCallback(
    (_: unknown, node: Node) => {
      onStepClick?.(node.id);
    },
    [onStepClick]
  );

  // 空状态
  if (!plan || !plan.steps || plan.steps.length === 0) {
    return (
      <div className="h-full flex items-center justify-center text-gray-400 text-sm">
        <div className="text-center">
          <Wrench className="w-10 h-10 mx-auto mb-2 opacity-30" />
          <p>暂无任务规划</p>
          <p className="text-xs mt-1">Agent 接收任务后将展示执行计划 DAG</p>
        </div>
      </div>
    );
  }

  return (
    <div className="h-full w-full">
      {plan.reasoning && (
        <div className="px-3 py-2 bg-gray-50 border-b border-gray-100 text-xs text-gray-600 italic">
          <span className="font-medium not-italic">规划理由：</span>
          {plan.reasoning}
        </div>
      )}
      <div className="h-[calc(100%-0px)]" style={{ minHeight: 300 }}>
        <ReactFlow
          nodes={nodes}
          edges={edges}
          nodeTypes={nodeTypes}
          onNodeClick={handleNodeClick}
          fitView
          fitViewOptions={{ padding: 0.2 }}
          nodesDraggable={false}
          nodesConnectable={false}
          elementsSelectable={true}
          proOptions={{ hideAttribution: true }}
        >
          <Background variant={BackgroundVariant.Dots} gap={16} size={1} color="#e2e8f0" />
          <Controls showInteractive={false} />
        </ReactFlow>
      </div>
    </div>
  );
}
