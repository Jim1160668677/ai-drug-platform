import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen } from '@testing-library/react';
import { renderWithProviders } from '@/lib/test-utils';
import DecisionChainList from './DecisionChainList';

vi.mock('@/lib/api', () => ({
  getDecisionChain: vi.fn(),
}));

import { getDecisionChain } from '@/lib/api';
const mockedGetDecisionChain = vi.mocked(getDecisionChain);

beforeEach(() => {
  vi.clearAllMocks();
});

describe('DecisionChainList', () => {
  it('加载中显示骨架', () => {
    mockedGetDecisionChain.mockReturnValue(new Promise(() => {}));
    renderWithProviders(<DecisionChainList runId="r1" />);
    expect(screen.getByText('决策链')).toBeInTheDocument();
  });

  it('空数据显示空状态', async () => {
    mockedGetDecisionChain.mockResolvedValue({ decisions: [] });
    renderWithProviders(<DecisionChainList runId="r1" />);
    expect(await screen.findByText('暂无决策记录')).toBeInTheDocument();
  });

  it('渲染决策列表', async () => {
    mockedGetDecisionChain.mockResolvedValue({
      decisions: [
        { decision_basis: '保持该假设', action: 'keep' },
        { decision_basis: '丢弃低分假设', action: 'discard' },
      ],
    });
    renderWithProviders(<DecisionChainList runId="r1" />);
    expect(await screen.findByText('决策链 (2)')).toBeInTheDocument();
    expect(screen.getByText('保持该假设')).toBeInTheDocument();
  });
});