import { render, screen } from '@testing-library/react';
import { FolderOpen } from 'lucide-react';
import EmptyState, { EmptyListState } from '@/components/ui/EmptyState';

describe('EmptyState', () => {
  it('renders title and description', () => {
    render(
      <EmptyState title="暂无数据" description="请创建新项目" />
    );
    expect(screen.getByText('暂无数据')).toBeInTheDocument();
    expect(screen.getByText('请创建新项目')).toBeInTheDocument();
  });

  it('renders action button when provided', () => {
    render(
      <EmptyState title="空" action={<button>新建</button>} />
    );
    expect(screen.getByRole('button', { name: '新建' })).toBeInTheDocument();
  });

  it('uses custom icon when provided', () => {
    render(
      <EmptyState title="空" icon={FolderOpen} />
    );
    const svg = document.querySelector('.lucide-folder-open');
    expect(svg).toBeInTheDocument();
  });

  it('applies custom className', () => {
    render(
      <EmptyState title="空" className="my-custom-class" />
    );
    const status = screen.getByRole('status');
    expect(status).toHaveClass('my-custom-class');
  });

  it('has aria-live for accessibility', () => {
    render(<EmptyState title="空" />);
    expect(screen.getByRole('status')).toHaveAttribute('aria-live', 'polite');
  });

  it('does not render description when not provided', () => {
    render(<EmptyState title="仅标题" />);
    expect(screen.queryByText('请创建')).not.toBeInTheDocument();
  });

  it('does not render action when not provided', () => {
    render(<EmptyState title="仅标题" />);
    expect(screen.queryByRole('button')).not.toBeInTheDocument();
  });
});

describe('EmptyListState', () => {
  it('renders with default title', () => {
    render(<EmptyListState />);
    expect(screen.getByText('暂无数据')).toBeInTheDocument();
  });

  it('renders with custom title and description', () => {
    render(
      <EmptyListState title="暂无假设" description="点击创建按钮新建假设" />
    );
    expect(screen.getByText('暂无假设')).toBeInTheDocument();
    expect(screen.getByText('点击创建按钮新建假设')).toBeInTheDocument();
  });
});
