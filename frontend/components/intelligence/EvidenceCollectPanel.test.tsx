import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, fireEvent, waitFor } from '@testing-library/react';
import { renderWithProviders } from '@/lib/test-utils';

vi.mock('@/lib/api', () => ({ collectEvidence: vi.fn() }));
vi.mock('@/lib/notification', () => ({ toast: { success: vi.fn(), error: vi.fn(), warning: vi.fn(), info: vi.fn() } }));
vi.mock('@/lib/store', () => ({
  useAppStore: (selector?: (s: { currentProject: { id: string; name: string } | null }) => unknown) => {
    const state = { currentProject: { id: 'p1', name: '测试项目' } };
    return selector ? selector(state) : state;
  },
}));

import { collectEvidence } from '@/lib/api';
const mockedCollectEvidence = vi.mocked(collectEvidence);
import EvidenceCollectPanel from './EvidenceCollectPanel';

beforeEach(() => { vi.clearAllMocks(); });

describe('EvidenceCollectPanel', () => {
  it('渲染表单并显示当前项目', () => {
    renderWithProviders(<EvidenceCollectPanel />);
    expect(screen.getByText('项目证据收集')).toBeInTheDocument();
    expect(screen.getByText(/测试项目/)).toBeInTheDocument();
  });

  it('空表单提交显示验证错误', () => {
    renderWithProviders(<EvidenceCollectPanel />);
    fireEvent.click(screen.getByText('收集证据'));
    expect(screen.getByText(/请至少填写一项/)).toBeInTheDocument();
  });

  it('填写触发事件后提交调用 API', async () => {
    mockedCollectEvidence.mockResolvedValue({ text: '结果', sources: [], total_items: 0 });
    renderWithProviders(<EvidenceCollectPanel />);
    const inputs = screen.getAllByRole('textbox');
    fireEvent.change(inputs[0], { target: { value: '靶点发现' } });
    fireEvent.click(screen.getByText('收集证据'));
    await waitFor(() => expect(mockedCollectEvidence).toHaveBeenCalled());
  });

  it('重置按钮清空表单', () => {
    renderWithProviders(<EvidenceCollectPanel />);
    const inputs = screen.getAllByRole('textbox');
    fireEvent.change(inputs[0], { target: { value: '测试' } });
    fireEvent.click(screen.getByText('重置'));
    expect(inputs[0]).toHaveValue('');
  });
});