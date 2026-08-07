import { describe, it, expect, vi } from 'vitest';
import { render, screen, fireEvent, waitFor } from '@testing-library/react';
import { renderWithProviders } from '@/lib/test-utils';

// mock react-virtuoso（jsdom 下不渲染列表内容）
vi.mock('react-virtuoso', () => ({
  Virtuoso: ({ data, itemContent }: { data: unknown[]; itemContent: (i: number, d: unknown) => React.ReactNode }) => (
    <div data-testid="mock-virtuoso">
      {data.map((d, i) => <div key={i}>{itemContent(i, d)}</div>)}
    </div>
  ),
  VirtuosoHandle: class {},
}));

// mock useAppStore 支持 selector
vi.mock('@/lib/store', () => ({
  useAppStore: (selector?: (s: { currentProject: { id: string; name: string } }) => unknown) => {
    const state = { currentProject: { id: 'p1', name: '项目1' } };
    return selector ? selector(state) : state;
  },
}));

import UnifiedChatPanel from './UnifiedChatPanel';
import type { IntelligenceMessage } from '@/types/intelligence';

const mockMessages: IntelligenceMessage[] = [
  { id: 'm1', role: 'user', content: '你好', timestamp: '2026-01-01T00:00:00Z' },
  { id: 'm2', role: 'assistant', content: '你好，有什么可以帮你？', timestamp: '2026-01-01T00:00:01Z', mode: 'chat' },
];

describe('UnifiedChatPanel', () => {
  it('渲染消息列表', () => {
    renderWithProviders(
      <UnifiedChatPanel sessionId="s1" messages={mockMessages} onSend={vi.fn()} isSending={false} />,
    );
    expect(screen.getByText('你好')).toBeInTheDocument();
    expect(screen.getByText('你好，有什么可以帮你？')).toBeInTheDocument();
  });

  it('输入并发送消息触发 onSend', () => {
    const onSend = vi.fn();
    renderWithProviders(
      <UnifiedChatPanel sessionId="s1" messages={[]} onSend={onSend} isSending={false} />,
    );
    const textarea = screen.getByPlaceholderText(/Enter.*发送/);
    fireEvent.change(textarea, { target: { value: '测试消息' } });
    fireEvent.keyDown(textarea, { key: 'Enter', shiftKey: false });
    expect(onSend).toHaveBeenCalledWith('测试消息', 'p1');
  });

  it('isSending=true 时不崩溃', () => {
    renderWithProviders(
      <UnifiedChatPanel sessionId="s1" messages={[]} onSend={vi.fn()} isSending={true} />,
    );
    expect(document.body).toBeInTheDocument();
  });
});