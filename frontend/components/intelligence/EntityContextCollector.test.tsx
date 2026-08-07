import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, fireEvent, waitFor } from '@testing-library/react';
import { renderWithProviders } from '@/lib/test-utils';

vi.mock('@/lib/api', () => ({ collectEntityContext: vi.fn() }));
vi.mock('@/lib/notification', () => ({ toast: { success: vi.fn(), error: vi.fn(), warning: vi.fn(), info: vi.fn() } }));
vi.mock('@/lib/store', () => ({
  useAppStore: (selector?: (s: { currentProject: { id: string; name: string } | null }) => unknown) => {
    const state = { currentProject: null };
    return selector ? selector(state) : state;
  },
}));

import { collectEntityContext } from '@/lib/api';
const mockedCollectEntityContext = vi.mocked(collectEntityContext);
import EntityContextCollector from './EntityContextCollector';

beforeEach(() => { vi.clearAllMocks(); });

describe('EntityContextCollector', () => {
  it('渲染表单', () => {
    renderWithProviders(<EntityContextCollector />);
    expect(screen.getByText('实体上下文收集')).toBeInTheDocument();
  });

  it('未填实体 ID 提交显示验证错误', () => {
    renderWithProviders(<EntityContextCollector />);
    fireEvent.click(screen.getByText('收集上下文'));
    expect(screen.getByText('请输入实体 ID')).toBeInTheDocument();
  });

  it('填写实体 ID 后提交调用 API', async () => {
    mockedCollectEntityContext.mockResolvedValue({ text: 'ctx', sources: [], total_items: 0 });
    renderWithProviders(<EntityContextCollector />);
    const input = screen.getByPlaceholderText(/靶点.*ID/);
    fireEvent.change(input, { target: { value: 'entity-123' } });
    fireEvent.click(screen.getByText('收集上下文'));
    await waitFor(() => expect(mockedCollectEntityContext).toHaveBeenCalled());
  });
});