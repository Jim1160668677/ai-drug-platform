import { describe, it, expect, vi } from 'vitest';
import { render, screen, fireEvent } from '@testing-library/react';
import Card from './Card';

describe('Card 组件', () => {
  describe('基础渲染', () => {
    it('渲染 children', () => {
      render(<Card>卡片内容</Card>);
      expect(screen.getByText('卡片内容')).toBeInTheDocument();
    });

    it('未提供 title 时不渲染 header', () => {
      const { container } = render(<Card>内容</Card>);
      // 没有 h3 标题
      expect(container.querySelector('h3')).toBeNull();
    });

    it('提供 title 时渲染 h3 标题', () => {
      render(<Card title="标题文本">内容</Card>);
      expect(screen.getByText('标题文本').tagName).toBe('H3');
    });
  });

  describe('action 槽', () => {
    it('未提供 title 时即使有 action 也不渲染 header', () => {
      const { container } = render(
        <Card action={<button>操作</button>}>内容</Card>
      );
      // 没有 header 区域（没有 h3）
      expect(container.querySelector('h3')).toBeNull();
      // action 按钮不应被渲染（因为在 header 内）
      expect(screen.queryByRole('button', { name: '操作' })).toBeNull();
    });

    it('提供 title + action 时两者都渲染', () => {
      render(
        <Card title="T" action={<button>操作</button>}>
          内容
        </Card>
      );
      expect(screen.getByText('T')).toBeInTheDocument();
      expect(screen.getByRole('button', { name: '操作' })).toBeInTheDocument();
    });
  });

  describe('onClick 交互', () => {
    it('点击触发 onClick', () => {
      const onClick = vi.fn();
      const { container } = render(<Card onClick={onClick}>内容</Card>);
      fireEvent.click(container.firstChild as HTMLElement);
      expect(onClick).toHaveBeenCalledTimes(1);
    });

    it('无 onClick 时不报错', () => {
      const { container } = render(<Card>内容</Card>);
      expect(() => fireEvent.click(container.firstChild as HTMLElement)).not.toThrow();
    });

    it('onClick 接收事件参数', () => {
      let received: any = null;
      const onClick = (e: any) => {
        received = e;
      };
      const { container } = render(<Card onClick={onClick}>内容</Card>);
      fireEvent.click(container.firstChild as HTMLElement);
      expect(received).toBeTruthy();
      expect(typeof received).toBe('object');
    });
  });

  describe('className 合并', () => {
    it('自定义 className 合并到默认样式', () => {
      const { container } = render(<Card className="mt-4 custom">内容</Card>);
      expect(container.firstChild).toHaveClass('mt-4');
      expect(container.firstChild).toHaveClass('custom');
      // 仍保留基础类
      expect(container.firstChild).toHaveClass('bg-white');
      expect(container.firstChild).toHaveClass('rounded-lg');
      expect(container.firstChild).toHaveClass('shadow-card');
      expect(container.firstChild).toHaveClass('border');
    });
  });

  describe('ReactNode children', () => {
    it('支持 JSX 元素作为 children', () => {
      render(
        <Card>
          <span data-testid="inner">内部</span>
        </Card>
      );
      expect(screen.getByTestId('inner')).toBeInTheDocument();
    });

    it('支持复杂结构 children', () => {
      render(
        <Card title="T">
          <div>
            <p>段落1</p>
            <p>段落2</p>
          </div>
        </Card>
      );
      expect(screen.getByText('段落1')).toBeInTheDocument();
      expect(screen.getByText('段落2')).toBeInTheDocument();
    });
  });
});
