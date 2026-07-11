import { describe, it, expect, vi } from 'vitest';
import { render, screen, fireEvent } from '@testing-library/react';
import Button from './Button';

describe('Button 组件', () => {
  describe('渲染与默认值', () => {
    it('渲染 children 文本', () => {
      render(<Button>点击我</Button>);
      expect(screen.getByRole('button', { name: '点击我' })).toBeInTheDocument();
    });

    it('默认 variant=primary 应用主色样式', () => {
      const { container } = render(<Button>X</Button>);
      expect(container.firstChild).toHaveClass('bg-primary-600');
      expect(container.firstChild).toHaveClass('text-white');
    });

    it('默认 size=md 应用中等尺寸样式', () => {
      const { container } = render(<Button>X</Button>);
      expect(container.firstChild).toHaveClass('px-4');
      expect(container.firstChild).toHaveClass('py-2');
      expect(container.firstChild).toHaveClass('text-sm');
    });
  });

  describe('variant 切换', () => {
    it('secondary variant', () => {
      const { container } = render(<Button variant="secondary">X</Button>);
      expect(container.firstChild).toHaveClass('bg-white');
      expect(container.firstChild).toHaveClass('border');
    });

    it('danger variant', () => {
      const { container } = render(<Button variant="danger">X</Button>);
      expect(container.firstChild).toHaveClass('bg-danger');
    });

    it('ghost variant', () => {
      const { container } = render(<Button variant="ghost">X</Button>);
      expect(container.firstChild).toHaveClass('text-gray-600');
    });
  });

  describe('size 切换', () => {
    it('sm size', () => {
      const { container } = render(<Button size="sm">X</Button>);
      expect(container.firstChild).toHaveClass('px-3');
      expect(container.firstChild).toHaveClass('py-1.5');
      expect(container.firstChild).toHaveClass('text-xs');
    });

    it('lg size', () => {
      const { container } = render(<Button size="lg">X</Button>);
      expect(container.firstChild).toHaveClass('px-6');
      expect(container.firstChild).toHaveClass('py-3');
      expect(container.firstChild).toHaveClass('text-base');
    });
  });

  describe('loading 状态', () => {
    it('loading=true 时按钮禁用', () => {
      render(<Button loading>X</Button>);
      expect(screen.getByRole('button')).toBeDisabled();
    });

    it('loading=true 时渲染 spinner svg', () => {
      const { container } = render(<Button loading>X</Button>);
      const button = container.firstChild as HTMLElement;
      const svg = button.querySelector('svg');
      expect(svg).toBeInTheDocument();
      expect(svg).toHaveClass('animate-spin');
    });

    it('loading 与 disabled 同时为 true 仍禁用', () => {
      render(
        <Button loading disabled>
          X
        </Button>
      );
      expect(screen.getByRole('button')).toBeDisabled();
    });
  });

  describe('disabled 状态', () => {
    it('disabled=true 时按钮禁用', () => {
      render(<Button disabled>X</Button>);
      expect(screen.getByRole('button')).toBeDisabled();
    });

    it('disabled 时点击不触发 onClick', () => {
      const onClick = vi.fn();
      render(
        <Button disabled onClick={onClick}>
          X
        </Button>
      );
      fireEvent.click(screen.getByRole('button'));
      expect(onClick).not.toHaveBeenCalled();
    });
  });

  describe('交互', () => {
    it('点击触发 onClick 回调', () => {
      const onClick = vi.fn();
      render(<Button onClick={onClick}>X</Button>);
      fireEvent.click(screen.getByRole('button'));
      expect(onClick).toHaveBeenCalledTimes(1);
    });

    it('透传原生 button 属性', () => {
      render(
        <Button type="button" data-testid="btn" aria-label="保存">
          X
        </Button>
      );
      const btn = screen.getByRole('button');
      expect(btn).toHaveAttribute('type', 'button');
      expect(btn).toHaveAttribute('data-testid', 'btn');
      expect(btn).toHaveAttribute('aria-label', '保存');
    });
  });

  describe('className 合并', () => {
    it('自定义 className 合并到默认样式', () => {
      const { container } = render(<Button className="my-4 w-full">X</Button>);
      expect(container.firstChild).toHaveClass('my-4');
      expect(container.firstChild).toHaveClass('w-full');
      // 仍保留基础类
      expect(container.firstChild).toHaveClass('inline-flex');
      expect(container.firstChild).toHaveClass('rounded-md');
    });
  });
});
