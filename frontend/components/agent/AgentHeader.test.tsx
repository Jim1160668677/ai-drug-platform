/**
 * AgentHeader 组件单元测试
 *
 * 设计来源：agent-test-case-matrix.md FE-C01~C03
 * 覆盖：默认渲染 / WS 状态指示器 / 任务状态徽章 / 取消按钮
 */
import { describe, it, expect, vi } from 'vitest';
import { render, screen, fireEvent } from '@testing-library/react';
import { AgentHeader } from './AgentHeader';
import type { TaskStatus } from '@/types/agent';

const defaultProps = {
  title: '测试会话',
  isRunning: false,
  onCancel: vi.fn(),
};

describe('AgentHeader 组件', () => {
  describe('FE-C01 默认渲染', () => {
    it('渲染标题', () => {
      render(<AgentHeader {...defaultProps} />);
      expect(screen.getByText('测试会话')).toBeInTheDocument();
    });

    it('无 taskStatus 时不显示状态徽章', () => {
      const { container } = render(<AgentHeader {...defaultProps} />);
      // 状态徽章有特定 class，无 taskStatus 时不存在
      const badges = container.querySelectorAll('.bg-gray-100, .bg-blue-100, .bg-green-100');
      // 可能有 WS 状态徽章（connected 默认），但任务状态徽章不应有
      expect(badges.length).toBeLessThanOrEqual(1);
    });

    it('显示 taskId 截断', () => {
      render(
        <AgentHeader
          {...defaultProps}
          currentTaskId="abcdef12-3456-7890-abcd-ef1234567890"
        />
      );
      expect(screen.getByText('#abcdef12')).toBeInTheDocument();
    });
  });

  describe('FE-C02 WebSocket 状态指示器', () => {
    it('wsStatus=connected 显示绿色已连接', () => {
      render(<AgentHeader {...defaultProps} wsStatus="connected" />);
      expect(screen.getByText('已连接')).toBeInTheDocument();
    });

    it('wsStatus=disconnected 显示红色已断开 + 橙色横幅', () => {
      render(
        <AgentHeader {...defaultProps} wsStatus="disconnected" />
      );
      expect(screen.getByText('已断开')).toBeInTheDocument();
      // 横幅
      expect(screen.getByText(/连接中断/)).toBeInTheDocument();
    });

    it('wsStatus=reconnecting 显示重连中 + 黄色横幅', () => {
      render(<AgentHeader {...defaultProps} wsStatus="reconnecting" />);
      expect(screen.getByText('重连中')).toBeInTheDocument();
      expect(screen.getByText(/正在重连/)).toBeInTheDocument();
    });

    it('wsStatus=connecting 显示连接中', () => {
      render(<AgentHeader {...defaultProps} wsStatus="connecting" />);
      expect(screen.getByText('连接中')).toBeInTheDocument();
    });
  });

  describe('FE-C03 任务状态徽章', () => {
    const statuses: TaskStatus[] = [
      'pending',
      'planning',
      'running',
      'awaiting_confirmation',
      'completed',
      'failed',
      'cancelled',
    ];

    statuses.forEach((status) => {
      it(`taskStatus=${status} 显示对应中文标签`, () => {
        render(<AgentHeader {...defaultProps} taskStatus={status} />);
        const labels: Record<TaskStatus, string> = {
          pending: '排队中',
          planning: '规划中',
          running: '执行中',
          awaiting_confirmation: '等待确认',
          completed: '已完成',
          failed: '失败',
          cancelled: '已取消',
        };
        expect(screen.getByText(labels[status])).toBeInTheDocument();
      });
    });

    it('isRunning=true 显示取消按钮', () => {
      const onCancel = vi.fn();
      render(<AgentHeader {...defaultProps} isRunning={true} onCancel={onCancel} />);
      const cancelBtn = screen.getByText('取消');
      fireEvent.click(cancelBtn);
      expect(onCancel).toHaveBeenCalledTimes(1);
    });

    it('isRunning=false 不显示取消按钮', () => {
      render(<AgentHeader {...defaultProps} isRunning={false} />);
      expect(screen.queryByText('取消')).not.toBeInTheDocument();
    });
  });

  describe('元数据展示', () => {
    it('tokenUsage.total > 0 显示 token 数', () => {
      render(
        <AgentHeader
          {...defaultProps}
          tokenUsage={{ prompt: 100, completion: 50, total: 150 }}
        />
      );
      expect(screen.getByText('150')).toBeInTheDocument();
    });

    it('costUsd > 0 显示成本', () => {
      render(<AgentHeader {...defaultProps} costUsd={0.0025} />);
      expect(screen.getByText('$0.0025')).toBeInTheDocument();
    });

    it('durationSec > 0 显示耗时', () => {
      render(<AgentHeader {...defaultProps} durationSec={3.5} />);
      expect(screen.getByText('3.5s')).toBeInTheDocument();
    });
  });
});
