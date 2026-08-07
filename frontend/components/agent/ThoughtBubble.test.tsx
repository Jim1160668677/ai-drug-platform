/**
 * ThoughtBubble 组件单元测试
 *
 * 设计来源：agent-test-case-matrix.md FE-C12~C13
 * 覆盖：折叠/展开 + 思考中动画 + 步数显示
 *
 * 关键行为：
 * - 默认折叠（除非 defaultExpanded=true 或 isThinking=true）
 * - 折叠时不显示 thought 内容，只显示 Thought 标签
 * - 步数格式："步骤 X/Y"（maxSteps 默认 15）
 * - isThinking=true 时显示"Agent 思考中"文案
 */
import { describe, it, expect } from 'vitest';
import { render, screen, fireEvent } from '@testing-library/react';
import { ThoughtBubble } from './ThoughtBubble';

describe('ThoughtBubble 组件', () => {
  describe('FE-C12 折叠/展开', () => {
    it('渲染 Thought 标签（折叠状态）', () => {
      render(<ThoughtBubble thought="分析靶点 EGFR 的可行性" />);
      expect(screen.getByText('Thought')).toBeInTheDocument();
    });

    it('默认折叠时不显示 thought 内容', () => {
      render(<ThoughtBubble thought="分析靶点 EGFR 的可行性" />);
      expect(screen.queryByText(/分析靶点/)).not.toBeInTheDocument();
    });

    it('显示步数（格式：步骤 X/Y）', () => {
      render(<ThoughtBubble thought="测试" step={3} maxSteps={10} />);
      expect(screen.getByText(/步骤 3\/10/)).toBeInTheDocument();
    });

    it('无 step 时不显示步数', () => {
      render(<ThoughtBubble thought="测试" />);
      expect(screen.queryByText(/步骤/)).not.toBeInTheDocument();
    });

    it('maxSteps 默认 15', () => {
      render(<ThoughtBubble thought="测试" step={2} />);
      expect(screen.getByText(/步骤 2\/15/)).toBeInTheDocument();
    });

    it('defaultExpanded=true 默认展开显示 thought 内容', () => {
      render(
        <ThoughtBubble thought="展开内容" defaultExpanded={true} />
      );
      expect(screen.getByText('展开内容')).toBeInTheDocument();
    });

    it('点击展开后显示 thought 内容', () => {
      render(<ThoughtBubble thought="点击展开" />);
      fireEvent.click(screen.getByRole('button'));
      expect(screen.getByText('点击展开')).toBeInTheDocument();
    });

    it('再次点击折叠已展开的内容', () => {
      render(<ThoughtBubble thought="测试" defaultExpanded={true} />);
      const btn = screen.getByRole('button');
      fireEvent.click(btn);
      expect(screen.queryByText('测试')).not.toBeInTheDocument();
    });
  });

  describe('FE-C13 思考中动画', () => {
    it('isThinking=true 显示"Agent 思考中"文案', () => {
      render(<ThoughtBubble thought="" isThinking={true} />);
      expect(screen.getByText('Agent 思考中')).toBeInTheDocument();
    });

    it('isThinking=true 时显示 Loader2 旋转图标（非 Brain）', () => {
      const { container } = render(
        <ThoughtBubble thought="" isThinking={true} />
      );
      const spinner = container.querySelector('.animate-spin');
      expect(spinner).toBeInTheDocument();
    });

    it('isThinking=true 且 thought 为空时显示打字指示器', () => {
      const { container } = render(
        <ThoughtBubble thought="" isThinking={true} />
      );
      // isThinking 强制展开，显示打字指示器
      const bounce = container.querySelector('.animate-bounce');
      expect(bounce).toBeInTheDocument();
    });

    it('isThinking=false 时不显示打字指示器', () => {
      const { container } = render(
        <ThoughtBubble thought="已完成" isThinking={false} defaultExpanded={true} />
      );
      const bounce = container.querySelector('.animate-bounce');
      expect(bounce).not.toBeInTheDocument();
    });

    it('isThinking=true 自动展开', () => {
      render(<ThoughtBubble thought="思考内容" isThinking={true} />);
      // isThinking 时默认展开，显示 thought
      expect(screen.getByText('思考内容')).toBeInTheDocument();
    });
  });

  describe('边界情况', () => {
    it('空 thought 不崩溃', () => {
      render(<ThoughtBubble thought="" />);
      expect(screen.getByText('Thought')).toBeInTheDocument();
    });

    it('超长 thought 不崩溃', () => {
      const veryLong = 'A'.repeat(10000);
      render(<ThoughtBubble thought={veryLong} defaultExpanded={true} />);
      expect(screen.getByText('Thought')).toBeInTheDocument();
    });

    it('特殊字符 thought 不崩溃', () => {
      render(
        <ThoughtBubble
          thought="<script>alert(1)</script>"
          defaultExpanded={true}
        />
      );
      expect(screen.getByText('Thought')).toBeInTheDocument();
    });
  });
});
