import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, fireEvent, waitFor } from '@testing-library/react';
import { renderWithProviders } from '@/lib/test-utils';

vi.mock('@/lib/api', () => ({ interpretAnalysis: vi.fn() }));
vi.mock('@/lib/notification', () => ({ toast: { success: vi.fn(), error: vi.fn(), warning: vi.fn(), info: vi.fn() } }));
vi.mock('@/lib/store', () => ({
  useAppStore: (selector?: (s: { currentProject: { id: string; name: string } | null }) => unknown) => {
    const state = { currentProject: { id: 'p1', name: '项目A' } };
    return selector ? selector(state) : state;
  },
}));

import { interpretAnalysis } from '@/lib/api';
const mockedInterpretAnalysis = vi.mocked(interpretAnalysis);
import AnalysisInterpretCard from './AnalysisInterpretCard';

beforeEach(() => { vi.clearAllMocks(); });

describe('AnalysisInterpretCard', () => {
  it('渲染表单', () => {
    renderWithProviders(<AnalysisInterpretCard />);
    expect(screen.getByText('统一解读分析')).toBeInTheDocument();
  });

  it('空问题提交显示验证错误', () => {
    renderWithProviders(<AnalysisInterpretCard />);
    fireEvent.click(screen.getByText('生成解读'));
    expect(screen.getByText('请输入分析问题')).toBeInTheDocument();
  });

  it('填写问题后提交调用 API', async () => {
    mockedInterpretAnalysis.mockResolvedValue({
      intent: 'test', conclusion: '结论', hypothesis: '假设',
      recommendations: [], key_findings: [], model: 'm1', cost_usd: 0, duration_sec: 1,
    });
    renderWithProviders(<AnalysisInterpretCard />);
    const textarea = screen.getByPlaceholderText(/差异表达基因/);
    fireEvent.change(textarea, { target: { value: '分析这个' } });
    fireEvent.click(screen.getByText('生成解读'));
    await waitFor(() => expect(mockedInterpretAnalysis).toHaveBeenCalled());
  });

  it('无效 JSON 提交显示错误', async () => {
    renderWithProviders(<AnalysisInterpretCard />);
    const textarea = screen.getByPlaceholderText(/差异表达基因/);
    fireEvent.change(textarea, { target: { value: '分析这个' } });
    const jsonInput = screen.getByPlaceholderText(/genes/);
    fireEvent.change(jsonInput, { target: { value: '{invalid' } });
    fireEvent.click(screen.getByText('生成解读'));
    await waitFor(() => expect(screen.getByText(/JSON/)).toBeInTheDocument());
    expect(mockedInterpretAnalysis).not.toHaveBeenCalled();
  });
});