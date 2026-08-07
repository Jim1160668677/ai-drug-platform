/**
 * ToolCallBubble 组件单元测试
 *
 * 设计来源：agent-test-case-matrix.md FE-C09~C11
 * 覆盖：pending/success/failed 状态 + 缓存命中标记 + 展开折叠
 */
import { describe, it, expect } from 'vitest';
import { render, screen, fireEvent } from '@testing-library/react';
import { ToolCallBubble } from './ToolCallBubble';
import type { ToolCall, ToolResult } from '@/types/agent';

const baseCall: ToolCall = {
  step: 1,
  tool: 'discover_targets',
  args: { gene: 'EGFR' },
};

describe('ToolCallBubble 组件', () => {
  describe('FE-C09 pending 状态', () => {
    it('无 result 时显示 Loader2 旋转图标', () => {
      const { container } = render(<ToolCallBubble call={baseCall} />);
      const spinner = container.querySelector('.animate-spin');
      expect(spinner).toBeInTheDocument();
    });

    it('显示工具名', () => {
      render(<ToolCallBubble call={baseCall} />);
      expect(screen.getByText('discover_targets')).toBeInTheDocument();
    });

    it('显示步数 #1', () => {
      render(<ToolCallBubble call={baseCall} />);
      expect(screen.getByText('#1')).toBeInTheDocument();
    });

    it('默认折叠，不显示 Parameters', () => {
      render(<ToolCallBubble call={baseCall} />);
      expect(screen.queryByText('Parameters')).not.toBeInTheDocument();
    });

    it('点击展开显示 Parameters 和 Thought', () => {
      render(<ToolCallBubble call={{ ...baseCall, thought: '思考中' }} />);
      fireEvent.click(screen.getByRole('button'));
      expect(screen.getByText('Parameters')).toBeInTheDocument();
      expect(screen.getByText('思考中')).toBeInTheDocument();
    });
  });

  describe('FE-C10 success + cache_hit', () => {
    const successResult: ToolResult = {
      step: 1,
      tool: 'discover_targets',
      success: true,
      data: { targets: ['EGFR', 'KRAS'] },
      duration_ms: 150,
    };

    it('success 显示绿色对勾', () => {
      const { container } = render(
        <ToolCallBubble call={baseCall} result={successResult} />
      );
      // CheckCircle2 图标存在
      const successIcon = container.querySelector('.text-green-500');
      expect(successIcon).toBeInTheDocument();
    });

    it('显示耗时', () => {
      render(<ToolCallBubble call={baseCall} result={successResult} />);
      expect(screen.getByText('150ms')).toBeInTheDocument();
    });

    it('cache_hit=true 显示缓存命中标记', () => {
      render(
        <ToolCallBubble
          call={baseCall}
          result={{ ...successResult, cache_hit: true }}
        />
      );
      expect(screen.getByText('缓存命中')).toBeInTheDocument();
    });

    it('cache_hit=true 时耗时显示 <1ms', () => {
      render(
        <ToolCallBubble
          call={baseCall}
          result={{ ...successResult, cache_hit: true }}
        />
      );
      expect(screen.getByText('<1ms')).toBeInTheDocument();
    });

    it('cache_hit=false 不显示缓存命中标记', () => {
      render(
        <ToolCallBubble
          call={baseCall}
          result={{ ...successResult, cache_hit: false }}
        />
      );
      expect(screen.queryByText('缓存命中')).not.toBeInTheDocument();
    });

    it('展开显示 Result 区域', () => {
      render(<ToolCallBubble call={baseCall} result={successResult} />);
      fireEvent.click(screen.getByRole('button'));
      expect(screen.getByText('Result')).toBeInTheDocument();
    });
  });

  describe('FE-C11 failed 状态', () => {
    const failedResult: ToolResult = {
      step: 1,
      tool: 'discover_targets',
      success: false,
      error: '数据库连接失败',
      duration_ms: 50,
    };

    it('failed 显示红色 X 图标', () => {
      const { container } = render(
        <ToolCallBubble call={baseCall} result={failedResult} />
      );
      const failIcon = container.querySelector('.text-red-500');
      expect(failIcon).toBeInTheDocument();
    });

    it('展开显示 Error 区域', () => {
      render(<ToolCallBubble call={baseCall} result={failedResult} />);
      fireEvent.click(screen.getByRole('button'));
      expect(screen.getByText('Error')).toBeInTheDocument();
    });

    it('failed 状态应用红色边框样式', () => {
      const { container } = render(
        <ToolCallBubble call={baseCall} result={failedResult} />
      );
      const bubble = container.firstChild as HTMLElement;
      expect(bubble.className).toContain('border-red-200');
      expect(bubble.className).toContain('bg-red-50');
    });
  });

  describe('交互', () => {
    it('再次点击折叠已展开的内容', () => {
      render(<ToolCallBubble call={baseCall} />);
      const btn = screen.getByRole('button');
      fireEvent.click(btn);
      expect(screen.getByText('Parameters')).toBeInTheDocument();
      fireEvent.click(btn);
      expect(screen.queryByText('Parameters')).not.toBeInTheDocument();
    });
  });
});
