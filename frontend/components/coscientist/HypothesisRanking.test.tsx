import { describe, it, expect, vi } from 'vitest';
import { render, screen } from '@testing-library/react';
import HypothesisRanking from './HypothesisRanking';

vi.mock('@tanstack/react-query', () => ({
  useQuery: () => ({
    data: {
      rankings: [
        {
          id: 'h1',
          name: 'H1',
          elo_score: 1015.0,
          experimental_elo_adjustment: 15.0,
          experimental_validation_count: 1,
          status: 'active',
        },
        {
          id: 'h2',
          name: 'H2',
          elo_score: 1000.0,
          status: 'active',
        },
      ],
      total_hypotheses: 2,
    },
    isLoading: false,
  }),
}));

vi.mock('@/lib/api', () => ({ getRankings: vi.fn() }));

describe('HypothesisRanking 验证徽章', () => {
  it('展示实验验证次数与累计 Elo 调整', () => {
    render(<HypothesisRanking runId="r1" />);
    expect(screen.getByText(/实验验证 ×1/)).toBeInTheDocument();
    expect(screen.getByText(/\+15.0 Elo/)).toBeInTheDocument();
  });

  it('无实验验证的假设不展示徽章', () => {
    render(<HypothesisRanking runId="r1" />);
    const badgeText = screen.queryByText(/实验验证/);
    expect(badgeText).not.toBeNull();
    expect(screen.getAllByText(/实验验证/)).toHaveLength(1);
  });
});
