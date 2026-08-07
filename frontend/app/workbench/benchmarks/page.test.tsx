/**
 * 基准评测页面测试
 *
 * 覆盖：
 * 1. 渲染标题和案例选择下拉
 * 2. 点击"对比 3 模式"触发 compareBenchmarks
 * 3. 成功后展示成本节省卡片
 * 4. 点击"跑全部 9 案例"触发 runAllBenchmarks
 * 5. 全部成功后展示 9 案例汇总
 * 6. API 失败时显示错误提示
 */
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { screen, fireEvent, waitFor, cleanup } from '@testing-library/react';
import BenchmarksPage from './page';
import { renderWithProviders } from '@/lib/test-utils';

// ===== mock API =====
const mockCompareBenchmarks = vi.fn();
const mockRunAllBenchmarks = vi.fn();

vi.mock('@/lib/api', async () => {
  const actual = await vi.importActual<typeof import('@/lib/api')>('@/lib/api');
  return {
    ...actual,
    compareBenchmarks: (...a: any[]) => mockCompareBenchmarks(...a),
    runAllBenchmarks: (...a: any[]) => mockRunAllBenchmarks(...a),
  };
});

// ===== fixture =====
const COMPARE_FIXTURE = {
  comparison: {
    cost_saving_pct: 75.5,
    speedup_factor: 12.3,
    energy_saving_pct: 99.1,
  },
  results: {
    hybrid: { metrics: { cost_usd: 0.02 } },
    traditional_supercompute: { metrics: { cost_usd: 2.5 } },
    llm_only: { metrics: { cost_usd: 0.5 } },
  },
  winner: 'hybrid',
};
const ALL_FIXTURE = {
  conclusion: 'hybrid 在 9/9 案例中胜出',
  summary: { hybrid_wins: 9, avg_cost_saving_pct: 78.5, avg_speedup_factor: 15.2 },
};

describe('BenchmarksPage', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mockCompareBenchmarks.mockResolvedValue(COMPARE_FIXTURE);
    mockRunAllBenchmarks.mockResolvedValue(ALL_FIXTURE);
  });
  afterEach(() => cleanup());

  it('渲染标题"基准评测"和案例选择下拉', () => {
    renderWithProviders(<BenchmarksPage />);
    expect(screen.getByText('基准评测')).toBeInTheDocument();
    expect(screen.getByText('案例选择')).toBeInTheDocument();
    expect(screen.getByText('对比 3 模式')).toBeInTheDocument();
    expect(screen.getByText('跑全部 9 案例')).toBeInTheDocument();
  });

  it('点击"对比 3 模式"触发 compareBenchmarks', async () => {
    renderWithProviders(<BenchmarksPage />);
    fireEvent.click(screen.getByText('对比 3 模式'));

    await waitFor(() => {
      expect(mockCompareBenchmarks).toHaveBeenCalled();
    });
    // 默认 caseId = 'aspirin'
    const callArgs = mockCompareBenchmarks.mock.calls[0][0];
    expect(callArgs.case_id).toBe('aspirin');
  });

  it('对比成功后展示成本节省/加速比/能耗节省卡片', async () => {
    renderWithProviders(<BenchmarksPage />);
    fireEvent.click(screen.getByText('对比 3 模式'));

    await waitFor(() => {
      expect(screen.getByText('成本节省')).toBeInTheDocument();
    });
    expect(screen.getByText('加速比')).toBeInTheDocument();
    expect(screen.getByText('能耗节省')).toBeInTheDocument();
    // cost_saving_pct=75.5 → "75.5%"
    expect(screen.getByText('75.5%')).toBeInTheDocument();
    // winner 显示在 "Winner:" 后
    expect(screen.getByText('Winner:')).toBeInTheDocument();
  });

  it('点击"跑全部 9 案例"触发 runAllBenchmarks', async () => {
    renderWithProviders(<BenchmarksPage />);
    fireEvent.click(screen.getByText('跑全部 9 案例'));

    await waitFor(() => {
      expect(mockRunAllBenchmarks).toHaveBeenCalled();
    });
  });

  it('全部成功后展示 9 案例汇总', async () => {
    renderWithProviders(<BenchmarksPage />);
    fireEvent.click(screen.getByText('跑全部 9 案例'));

    await waitFor(() => {
      expect(screen.getByText('9 案例汇总')).toBeInTheDocument();
    });
    expect(screen.getByText('Hybrid 胜出')).toBeInTheDocument();
    expect(screen.getByText('平均成本节省')).toBeInTheDocument();
    expect(screen.getByText('平均加速')).toBeInTheDocument();
  });

  it('compareBenchmarks 失败时显示错误提示', async () => {
    mockCompareBenchmarks.mockRejectedValueOnce({
      response: { data: { detail: '基准评测引擎不可用' } },
    });
    renderWithProviders(<BenchmarksPage />);
    fireEvent.click(screen.getByText('对比 3 模式'));

    await waitFor(() => {
      expect(screen.getByText('基准评测引擎不可用')).toBeInTheDocument();
    });
  });
});
