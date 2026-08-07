import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, fireEvent, waitFor } from '@testing-library/react';
import { renderWithProviders } from '@/lib/test-utils';

vi.mock('@/lib/api', () => ({ interpretDataset: vi.fn() }));
vi.mock('@/lib/notification', () => ({ toast: { success: vi.fn(), error: vi.fn(), warning: vi.fn(), info: vi.fn() } }));
vi.mock('@/lib/store', () => ({
  useAppStore: (selector?: (s: { currentProject: { id: string; name: string } | null }) => unknown) => {
    const state = { currentProject: { id: 'p1', name: '项目A' } };
    return selector ? selector(state) : state;
  },
}));

import { interpretDataset } from '@/lib/api';
const mockedInterpretDataset = vi.mocked(interpretDataset);
import DatasetInterpretCard from './DatasetInterpretCard';

beforeEach(() => { vi.clearAllMocks(); });

describe('DatasetInterpretCard', () => {
  it('渲染表单', () => {
    renderWithProviders(<DatasetInterpretCard />);
    expect(screen.getByText('数据集解读')).toBeInTheDocument();
  });

  it('未填数据集 ID 提交显示验证错误', () => {
    renderWithProviders(<DatasetInterpretCard />);
    fireEvent.click(screen.getByText('解读数据集'));
    expect(screen.getByText('请输入数据集 ID')).toBeInTheDocument();
  });

  it('填写 ID 后提交调用 API', async () => {
    mockedInterpretDataset.mockResolvedValue({
      intent: 'dataset', conclusion: '结论', hypothesis: '假设',
      recommendations: [], key_findings: [], model: 'm1', cost_usd: 0, duration_sec: 1,
    });
    renderWithProviders(<DatasetInterpretCard />);
    const input = screen.getByPlaceholderText(/UUID/);
    fireEvent.change(input, { target: { value: 'ds-123' } });
    fireEvent.click(screen.getByText('解读数据集'));
    await waitFor(() => expect(mockedInterpretDataset).toHaveBeenCalledWith('ds-123', expect.any(Object)));
  });
});