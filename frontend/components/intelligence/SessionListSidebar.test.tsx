import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, fireEvent } from '@testing-library/react';
import { renderWithProviders } from '@/lib/test-utils';

vi.mock('@/lib/api', () => ({
  createSession: vi.fn(),
  listSessions: vi.fn(),
  archiveSession: vi.fn(),
}));

vi.mock('@/lib/store', () => ({
  useAppStore: () => ({ currentProject: { id: 'p1', name: '项目1' } }),
}));

vi.mock('@/lib/notification', () => ({
  toast: { success: vi.fn(), error: vi.fn(), warning: vi.fn(), info: vi.fn() },
}));

import { listSessions, createSession } from '@/lib/api';
const mockedListSessions = vi.mocked(listSessions);
const mockedCreateSession = vi.mocked(createSession);

import SessionListSidebar from './SessionListSidebar';

beforeEach(() => {
  vi.clearAllMocks();
  mockedListSessions.mockResolvedValue({
    items: [
      { id: 's1', title: '会话1', status: 'active', primary_mode: 'chat', message_count: 5, created_at: '2026-01-01T00:00:00Z', updated_at: '2026-01-01T00:00:00Z', user_id: 'u1' },
    ],
    total: 1,
  });
});

describe('SessionListSidebar', () => {
  it('渲染会话列表', async () => {
    renderWithProviders(<SessionListSidebar />);
    expect(await screen.findByText('会话1')).toBeInTheDocument();
  });

  it('点击会话触发 onSelect', async () => {
    const onSelect = vi.fn();
    renderWithProviders(<SessionListSidebar onSelect={onSelect} />);
    const item = await screen.findByText('会话1');
    fireEvent.click(item);
    expect(onSelect).toHaveBeenCalledWith('s1');
  });

  it('新建按钮存在', async () => {
    renderWithProviders(<SessionListSidebar />);
    expect(await screen.findByText('会话1')).toBeInTheDocument();
    // 新建按钮（Plus 图标）
    const buttons = screen.getAllByRole('button');
    expect(buttons.length).toBeGreaterThan(0);
  });
});