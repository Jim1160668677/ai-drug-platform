import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen } from '@testing-library/react';
import { renderWithProviders } from '@/lib/test-utils';

// mock next/dynamic 返回占位组件（避免 plotly 在 jsdom 下加载）
vi.mock('next/dynamic', () => ({
  default: () => {
    const MockPlot = () => <div data-testid="mock-plot" />;
    return MockPlot;
  },
}));

vi.mock('@/lib/api', () => ({
  getCostBreakdown: vi.fn(),
}));

import { getCostBreakdown } from '@/lib/api';
const mockedGetCostBreakdown = vi.mocked(getCostBreakdown);

import CostBreakdownChart from './CostBreakdownChart';

beforeEach(() => {
  vi.clearAllMocks();
});

describe('CostBreakdownChart', () => {
  it('加载中显示提示', () => {
    mockedGetCostBreakdown.mockReturnValue(new Promise(() => {}));
    renderWithProviders(<CostBreakdownChart runId="r1" />);
    expect(screen.getByText('成本分解')).toBeInTheDocument();
  });

  it('空数据显示空状态', async () => {
    mockedGetCostBreakdown.mockResolvedValue(null as unknown as Awaited<ReturnType<typeof getCostBreakdown>>);
    renderWithProviders(<CostBreakdownChart runId="r1" />);
    expect(await screen.findByText('暂无成本数据')).toBeInTheDocument();
  });

  it('渲染成本汇总不崩溃', async () => {
    mockedGetCostBreakdown.mockResolvedValue({
      total_cost: 0.1234,
      total_tokens: 5000,
      by_agent: { agnes: 0.08, glm: 0.04 },
      by_phase: { generation: 0.05, ranking: 0.07 },
      by_step_type: { llm_call: 0.1, tool_call: 0.02 },
    });
    renderWithProviders(<CostBreakdownChart runId="r1" />);
    expect(await screen.findByText('成本分解')).toBeInTheDocument();
    expect(screen.getByText('$0.1234')).toBeInTheDocument();
  });
});