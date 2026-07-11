import { describe, it, expect } from 'vitest';
import { render, screen } from '@testing-library/react';
import Loading, { LoadingRow, LoadingCard } from './Loading';

describe('Loading 组件', () => {
  describe('基础渲染', () => {
    it('渲染 spinner svg', () => {
      const { container } = render(<Loading />);
      expect(container.querySelector('svg')).toBeInTheDocument();
    });

    it('默认 size=md 应用 h-6 w-6', () => {
      const { container } = render(<Loading />);
      expect(container.querySelector('svg')).toHaveClass('h-6');
      expect(container.querySelector('svg')).toHaveClass('w-6');
    });

    it('应用 animate-spin 类', () => {
      const { container } = render(<Loading />);
      expect(container.querySelector('svg')).toHaveClass('animate-spin');
    });

    it('应用主色 text-primary-600', () => {
      const { container } = render(<Loading />);
      expect(container.querySelector('svg')).toHaveClass('text-primary-600');
    });
  });

  describe('size 切换', () => {
    it('sm size 应用 h-4 w-4', () => {
      const { container } = render(<Loading size="sm" />);
      expect(container.querySelector('svg')).toHaveClass('h-4');
      expect(container.querySelector('svg')).toHaveClass('w-4');
    });

    it('lg size 应用 h-10 w-10', () => {
      const { container } = render(<Loading size="lg" />);
      expect(container.querySelector('svg')).toHaveClass('h-10');
      expect(container.querySelector('svg')).toHaveClass('w-10');
    });
  });

  describe('label', () => {
    it('未提供 label 时不渲染 p 标签', () => {
      const { container } = render(<Loading />);
      expect(container.querySelector('p')).toBeNull();
    });

    it('提供 label 时渲染文本', () => {
      render(<Loading label="加载中..." />);
      expect(screen.getByText('加载中...')).toBeInTheDocument();
    });

    it('label 应用灰色文本样式', () => {
      render(<Loading label="加载中" />);
      expect(screen.getByText('加载中')).toHaveClass('text-gray-500');
      expect(screen.getByText('加载中')).toHaveClass('text-sm');
    });
  });

  describe('fullscreen 模式', () => {
    it('fullscreen=false 时（默认）不渲染遮罩', () => {
      const { container } = render(<Loading />);
      // 默认不包含 fixed 类
      const root = container.firstChild as HTMLElement;
      expect(root.className).not.toContain('fixed');
    });

    it('fullscreen=true 时渲染全屏遮罩', () => {
      const { container } = render(<Loading fullscreen />);
      const root = container.firstChild as HTMLElement;
      expect(root).toHaveClass('fixed');
      expect(root).toHaveClass('inset-0');
      expect(root).toHaveClass('z-50');
    });

    it('fullscreen 时仍包含 spinner', () => {
      const { container } = render(<Loading fullscreen label="加载" />);
      expect(container.querySelector('svg')).toBeInTheDocument();
      expect(screen.getByText('加载')).toBeInTheDocument();
    });
  });

  describe('className 合并', () => {
    it('自定义 className 被合并', () => {
      const { container } = render(<Loading className="my-4" />);
      expect(container.firstChild).toHaveClass('my-4');
    });
  });
});

describe('LoadingRow 组件', () => {
  it('默认渲染 5 列', () => {
    const { container } = render(
      <table>
        <tbody>
          <LoadingRow />
        </tbody>
      </table>
    );
    expect(container.querySelectorAll('td')).toHaveLength(5);
  });

  it('自定义 cols 数量', () => {
    const { container } = render(
      <table>
        <tbody>
          <LoadingRow cols={3} />
        </tbody>
      </table>
    );
    expect(container.querySelectorAll('td')).toHaveLength(3);
  });

  it('cols=0 时不渲染 td', () => {
    const { container } = render(
      <table>
        <tbody>
          <LoadingRow cols={0} />
        </tbody>
      </table>
    );
    expect(container.querySelectorAll('td')).toHaveLength(0);
  });

  it('每个 td 内有 animate-pulse 占位元素', () => {
    const { container } = render(
      <table>
        <tbody>
          <LoadingRow cols={2} />
        </tbody>
      </table>
    );
    const pulse = container.querySelectorAll('.animate-pulse');
    expect(pulse).toHaveLength(2);
  });

  it('渲染为 tr 元素', () => {
    const { container } = render(
      <table>
        <tbody>
          <LoadingRow />
        </tbody>
      </table>
    );
    expect(container.querySelector('tr')).toBeInTheDocument();
  });
});

describe('LoadingCard 组件', () => {
  it('渲染卡片容器', () => {
    const { container } = render(<LoadingCard />);
    expect(container.firstChild).toBeInTheDocument();
  });

  it('包含多个 animate-pulse 占位元素', () => {
    const { container } = render(<LoadingCard />);
    const pulse = container.querySelectorAll('.animate-pulse');
    // 至少 4 个占位
    expect(pulse.length).toBeGreaterThanOrEqual(4);
  });

  it('应用卡片样式', () => {
    const { container } = render(<LoadingCard />);
    expect(container.firstChild).toHaveClass('rounded-xl');
    expect(container.firstChild).toHaveClass('border');
    expect(container.firstChild).toHaveClass('bg-white');
    expect(container.firstChild).toHaveClass('shadow-sm');
  });
});
