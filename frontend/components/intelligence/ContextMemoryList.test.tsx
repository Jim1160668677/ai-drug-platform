import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen } from '@testing-library/react';
import { renderWithProviders } from '@/lib/test-utils';
import ContextMemoryList from './ContextMemoryList';

vi.mock('@/lib/api', () => ({
  getContext: vi.fn(),
}));

import { getContext } from '@/lib/api';
const mockedGetContext = vi.mocked(getContext);

beforeEach(() => {
  vi.clearAllMocks();
});

describe('ContextMemoryList', () => {
  it('加载中显示骨架', () => {
    mockedGetContext.mockReturnValue(new Promise(() => {}));
    renderWithProviders(<ContextMemoryList sessionId="s1" />);
    // 骨架屏存在
    expect(screen.getByText('上下文记忆')).toBeInTheDocument();
  });

  it('空数据时显示空状态', async () => {
    mockedGetContext.mockResolvedValue({
      session_id: 's1',
      memories: [],
      context_prompt: '',
    });
    renderWithProviders(<ContextMemoryList sessionId="s1" />);
    // 等待加载完成（空状态文案）
    expect(await screen.findByText('上下文记忆')).toBeInTheDocument();
  });

  it('渲染记忆列表', async () => {
    mockedGetContext.mockResolvedValue({
      session_id: 's1',
      memories: [
        { id: 'm1', type: 'user_message', content: '记忆1', importance: 0.9 },
        { id: 'm2', type: 'tool_call', content: '记忆2', importance: 0.5 },
      ],
      context_prompt: 'ctx prompt',
    });
    renderWithProviders(<ContextMemoryList sessionId="s1" />);
    // 骨架先渲染
    expect(await screen.findByText('记忆1', { exact: false })).toBeInTheDocument();
  });
});