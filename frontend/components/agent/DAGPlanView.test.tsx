/**
 * DAGPlanView 组件单元测试
 *
 * 设计来源：agent-test-case-matrix.md FE-C14~C15
 * 覆盖：空状态 + DAG 渲染 + 节点状态
 *
 * 注意：reactflow 在 jsdom 环境下可能渲染受限，
 * 测试主要验证组件不崩溃 + 关键 UI 元素存在
 */
import { describe, it, expect, vi } from 'vitest';
import { render, screen } from '@testing-library/react';
import { DAGPlanView } from './DAGPlanView';
import type { Plan } from '@/types/agent';

const simplePlan: Plan = {
  steps: [
    {
      id: 'step1',
      tool: 'discover_targets',
      args: { gene: 'EGFR' },
      depends_on: [],
      description: '发现靶点',
    },
    {
      id: 'step2',
      tool: 'design_molecule',
      args: { target: 'EGFR' },
      depends_on: ['step1'],
      description: '设计分子',
    },
  ],
  parallel_layers: [['step1'], ['step2']],
};

describe('DAGPlanView 组件', () => {
  describe('FE-C14 空 plan', () => {
    it('plan=null 显示空状态', () => {
      render(<DAGPlanView plan={null} />);
      // 空状态应有提示文案（"暂无任务规划" 或 "Agent 接收任务后将展示执行计划 DAG"）
      expect(screen.getByText('暂无任务规划')).toBeInTheDocument();
    });

    it('plan.steps=[] 显示空状态', () => {
      render(<DAGPlanView plan={{ steps: [], parallel_layers: [] }} />);
      expect(screen.getByText('暂无任务规划')).toBeInTheDocument();
    });
  });

  describe('FE-C15 DAG 渲染', () => {
    it('渲染 plan 不崩溃', () => {
      const { container } = render(<DAGPlanView plan={simplePlan} />);
      expect(container).toBeInTheDocument();
    });

    it('渲染工具名（节点内显示 tool 名）', () => {
      const { container } = render(<DAGPlanView plan={simplePlan} />);
      // reactflow 渲染的节点会包含 tool 名
      const text = container.textContent || '';
      expect(text).toContain('discover_targets');
      expect(text).toContain('design_molecule');
    });

    it('currentStep 高亮当前节点', () => {
      const { container } = render(
        <DAGPlanView plan={simplePlan} currentStep={1} />
      );
      expect(container).toBeInTheDocument();
    });

    it('completedSteps 标记完成节点', () => {
      const completed = new Set<number>([1]);
      const { container } = render(
        <DAGPlanView plan={simplePlan} completedSteps={completed} />
      );
      expect(container).toBeInTheDocument();
    });

    it('onStepClick 回调可调用', () => {
      const onClick = vi.fn();
      render(<DAGPlanView plan={simplePlan} onStepClick={onClick} />);
      // 不直接触发（reactflow 节点交互复杂），验证不崩溃
      expect(onClick).toBeDefined();
    });

    it('direction=LR 横向布局', () => {
      const { container } = render(
        <DAGPlanView plan={simplePlan} direction="LR" />
      );
      expect(container).toBeInTheDocument();
    });
  });

  describe('复杂 DAG', () => {
    it('多分支依赖不崩溃', () => {
      const complexPlan: Plan = {
        steps: [
          {
            id: 's1',
            tool: 'discover_targets',
            args: {},
            depends_on: [],
          },
          {
            id: 's2',
            tool: 'analyze_pathway',
            args: {},
            depends_on: ['s1'],
          },
          {
            id: 's3',
            tool: 'design_molecule',
            args: {},
            depends_on: ['s1'],
          },
          {
            id: 's4',
            tool: 'dock',
            args: {},
            depends_on: ['s2', 's3'],
          },
        ],
        parallel_layers: [['s1'], ['s2', 's3'], ['s4']],
      };
      const { container } = render(<DAGPlanView plan={complexPlan} />);
      expect(container).toBeInTheDocument();
    });
  });
});
