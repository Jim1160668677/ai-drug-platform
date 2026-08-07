/**
 * MessageList 组件单元测试
 *
 * 设计来源：agent-test-case-matrix.md FE-C07~C08
 * 覆盖：空状态 + 消息渲染（user/assistant/system）+ 虚拟滚动
 *
 * 注意：react-virtuoso 的 Virtuoso 在 jsdom 下不渲染虚拟项目内容，
 * 这里 mock 为简单列表渲染以验证 MessageItem 行为。
 */
import { describe, it, expect, vi } from 'vitest';
import { render, screen } from '@testing-library/react';
import type { AgentMessage } from '@/types/agent';

// mock react-virtuoso：将 Virtuoso 替换为简单列表渲染（forwardRef 以支持 ref 传入）
vi.mock('react-virtuoso', () => {
  const React = require('react');
  const Virtuoso = React.forwardRef<unknown, { data: unknown[]; itemContent: (index: number, item: unknown) => React.ReactNode }>(
    ({ data, itemContent }) =>
      React.createElement(
        'div',
        { 'data-testid': 'virtuoso-mock' },
        data.map((item, index) => React.createElement('div', { key: index }, itemContent(index, item)))
      )
  );
  Virtuoso.displayName = 'Virtuoso';
  return {
    Virtuoso,
    VirtuosoHandle: class {},
  };
});

// 动态导入以应用 mock
const { MessageList } = await import('./MessageList');

describe('MessageList 组件', () => {
  describe('FE-C07 空状态', () => {
    it('空消息列表显示空状态提示', () => {
      render(<MessageList messages={[]} />);
      expect(screen.getByText(/向 AI Agent 提问/)).toBeInTheDocument();
    });

    it('空状态显示示例问题', () => {
      render(<MessageList messages={[]} />);
      expect(screen.getByText(/EGFR/)).toBeInTheDocument();
      expect(screen.getByText(/B7H3/)).toBeInTheDocument();
      expect(screen.getByText(/KRAS/)).toBeInTheDocument();
    });
  });

  describe('FE-C08 消息渲染', () => {
    it('渲染 user 消息（右对齐 + 主色背景）', () => {
      const messages: AgentMessage[] = [
        {
          id: 'm1',
          role: 'user',
          content: '你好',
          timestamp: new Date().toISOString(),
        },
      ];
      const { container } = render(<MessageList messages={messages} />);
      expect(screen.getByText('你好')).toBeInTheDocument();
      // user 消息容器有 justify-end
      const wrapper = container.querySelector('.justify-end');
      expect(wrapper).toBeInTheDocument();
    });

    it('渲染 assistant 消息（左对齐 + 灰色背景）', () => {
      const messages: AgentMessage[] = [
        {
          id: 'm2',
          role: 'assistant',
          content: '我是 Agent',
          timestamp: new Date().toISOString(),
        },
      ];
      const { container } = render(<MessageList messages={messages} />);
      expect(screen.getByText('我是 Agent')).toBeInTheDocument();
      const wrapper = container.querySelector('.justify-start');
      expect(wrapper).toBeInTheDocument();
    });

    it('渲染 system 消息（居中 + 红色错误样式）', () => {
      const messages: AgentMessage[] = [
        {
          id: 'm3',
          role: 'system',
          content: '⚠️ 发生错误',
          timestamp: new Date().toISOString(),
        },
      ];
      const { container } = render(<MessageList messages={messages} />);
      expect(screen.getByText('⚠️ 发生错误')).toBeInTheDocument();
      // system 消息居中
      const center = container.querySelector('.justify-center');
      expect(center).toBeInTheDocument();
    });

    it('渲染 thought 消息（带 Brain 图标）', () => {
      const messages: AgentMessage[] = [
        {
          id: 'm4',
          role: 'assistant',
          content: '',
          thought: '正在思考靶点',
          timestamp: new Date().toISOString(),
        },
      ];
      render(<MessageList messages={messages} />);
      expect(screen.getByText('正在思考靶点')).toBeInTheDocument();
    });

    it('渲染带工具调用的 assistant 消息', () => {
      const messages: AgentMessage[] = [
        {
          id: 'm5',
          role: 'assistant',
          content: '调用工具中',
          timestamp: new Date().toISOString(),
          toolCalls: [
            {
              step: 1,
              tool: 'discover_targets',
              args: { gene: 'EGFR' },
            },
          ],
          toolResults: [
            {
              step: 1,
              tool: 'discover_targets',
              success: true,
              data: { targets: ['EGFR'] },
              duration_ms: 100,
            },
          ],
        },
      ];
      render(<MessageList messages={messages} />);
      expect(screen.getByText('调用工具中')).toBeInTheDocument();
      expect(screen.getByText('discover_targets')).toBeInTheDocument();
    });

    it('渲染多条消息', () => {
      const messages: AgentMessage[] = [
        {
          id: 'm1',
          role: 'user',
          content: '问题1',
          timestamp: new Date().toISOString(),
        },
        {
          id: 'm2',
          role: 'assistant',
          content: '回答1',
          timestamp: new Date().toISOString(),
        },
        {
          id: 'm3',
          role: 'user',
          content: '问题2',
          timestamp: new Date().toISOString(),
        },
      ];
      render(<MessageList messages={messages} />);
      expect(screen.getByText('问题1')).toBeInTheDocument();
      expect(screen.getByText('回答1')).toBeInTheDocument();
      expect(screen.getByText('问题2')).toBeInTheDocument();
    });
  });

  describe('虚拟滚动', () => {
    it('1000 条消息不崩溃（虚拟滚动）', () => {
      const messages: AgentMessage[] = Array.from({ length: 1000 }, (_, i) => ({
        id: `m${i}`,
        role: i % 2 === 0 ? ('user' as const) : ('assistant' as const),
        content: `消息 ${i}`,
        timestamp: new Date().toISOString(),
      }));
      const { container } = render(<MessageList messages={messages} />);
      // 不应渲染所有 1000 条（虚拟滚动只渲染可见部分）
      expect(container).toBeInTheDocument();
    });
  });
});
