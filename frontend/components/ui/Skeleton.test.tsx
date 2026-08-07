import { render } from '@testing-library/react';
import Skeleton, { SkeletonText, SkeletonRow, SkeletonCard, SkeletonList } from '@/components/ui/Skeleton';

describe('Skeleton', () => {
  it('renders with default classes', () => {
    const { container } = render(<Skeleton />);
    const skeleton = container.firstChild as HTMLElement;
    expect(skeleton).toHaveClass('animate-pulse', 'bg-gray-200', 'rounded');
  });

  it('applies circle class when circle=true', () => {
    const { container } = render(<Skeleton circle />);
    expect(container.firstChild).toHaveClass('rounded-full');
  });

  it('applies custom className', () => {
    const { container } = render(<Skeleton className="h-4 w-full" />);
    expect(container.firstChild).toHaveClass('h-4', 'w-full');
  });

  it('has aria-hidden for accessibility', () => {
    const { container } = render(<Skeleton />);
    expect(container.firstChild).toHaveAttribute('aria-hidden', 'true');
  });
});

describe('SkeletonText', () => {
  it('renders default 3 lines', () => {
    const { container } = render(<SkeletonText />);
    const skeletons = container.querySelectorAll('.animate-pulse');
    expect(skeletons).toHaveLength(3);
  });

  it('renders custom number of lines', () => {
    const { container } = render(<SkeletonText lines={5} />);
    const skeletons = container.querySelectorAll('.animate-pulse');
    expect(skeletons).toHaveLength(5);
  });

  it('last line is shorter (w-2/3)', () => {
    const { container } = render(<SkeletonText lines={3} />);
    const skeletons = container.querySelectorAll('.animate-pulse');
    expect(skeletons[2]).toHaveClass('w-2/3');
    expect(skeletons[0]).toHaveClass('w-full');
  });
});

describe('SkeletonRow', () => {
  it('renders default 5 columns', () => {
    const { container } = render(
      <table><tbody><SkeletonRow /></tbody></table>
    );
    const cells = container.querySelectorAll('td');
    expect(cells).toHaveLength(5);
  });

  it('renders custom columns', () => {
    const { container } = render(
      <table><tbody><SkeletonRow cols={3} /></tbody></table>
    );
    const cells = container.querySelectorAll('td');
    expect(cells).toHaveLength(3);
  });
});

describe('SkeletonCard', () => {
  it('renders card structure', () => {
    const { container } = render(<SkeletonCard />);
    const card = container.firstChild as HTMLElement;
    expect(card).toHaveClass('rounded-xl', 'border', 'bg-white', 'p-5');
    const skeletons = container.querySelectorAll('.animate-pulse');
    expect(skeletons.length).toBeGreaterThanOrEqual(4);
  });
});

describe('SkeletonList', () => {
  it('renders default 3 items', () => {
    const { container } = render(<SkeletonList />);
    const items = container.querySelectorAll('[class*="border"][class*="rounded-lg"]');
    expect(items).toHaveLength(3);
  });

  it('renders custom count', () => {
    const { container } = render(<SkeletonList count={5} />);
    const items = container.querySelectorAll('[class*="border"][class*="rounded-lg"]');
    expect(items).toHaveLength(5);
  });
});
