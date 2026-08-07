import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen } from '@testing-library/react';
import { renderWithProviders } from '@/lib/test-utils';

vi.mock('@/lib/api', () => ({
  getSession: vi.fn(),
}));

import { getSession } from '@/lib/api';
const mockedGetSession = vi.mocked(getSession);
import SessionMetaCard from './SessionMetaCard';

beforeEach(() => {
  vi.clearAllMocks();
});

describe('SessionMetaCard', () => {
  it('加载中渲染骨架不崩溃', () => {
    mockedGetSession.mockReturnValue(new Promise(() => {}));
    const { container } = renderWithProviders(<SessionMetaCard sessionId="s1" />);
    expect(container).toBeInTheDocument();
  });

  it('渲染会话元信息', async () => {
    mockedGetSession.mockResolvedValue({
      id: 's1', user_id: 'u1', title: '测试会话', status: 'active',
      primary_mode: 'chat', message_count: 10,
      created_at: '2026-01-01T00:00:00Z', updated_at: '2026-01-01T00:00:00Z',
    });
    renderWithProviders(<SessionMetaCard sessionId="s1" />);
    expect(await screen.findByText('测试会话')).toBeInTheDocument();
    expect(screen.getByText('10 条消息')).toBeInTheDocument();
  });
});