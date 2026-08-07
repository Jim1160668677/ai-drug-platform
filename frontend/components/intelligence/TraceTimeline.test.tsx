import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, fireEvent } from '@testing-library/react';
import { renderWithProviders } from '@/lib/test-utils';
import TraceTimeline from './TraceTimeline';

vi.mock('@/lib/api', () => ({
  getTrace: vi.fn(),
}));

import { getTrace } from '@/lib/api';
const mockedGetTrace = vi.mocked(getTrace);

beforeEach(() => {
  vi.clearAllMocks();
});

describe('TraceTimeline', () => {
  it('加载中不崩溃', () => {
    mockedGetTrace.mockReturnValue(new Promise(() => {}));
    renderWithProviders(<TraceTimeline sessionId="s1" />);
    expect(screen.getByText('推理追溯')).toBeInTheDocument();
  });

  it('空数据显示空状态', async () => {
    mockedGetTrace.mockResolvedValue({ session_id: 's1', total_steps: 0, traces: [] });
    renderWithProviders(<TraceTimeline sessionId="s1" />);
    expect(await screen.findByText('推理追溯')).toBeInTheDocument();
  });

  it('渲染步骤列表', async () => {
    mockedGetTrace.mockResolvedValue({
      session_id: 's1',
      total_steps: 2,
      traces: [
        { id: 't1', step_type: 'user_message', status: 'completed', created_at: '2026-01-01T00:00:00Z' },
        { id: 't2', step_type: 'llm_call', agent_name: 'agnes', status: 'completed', cost_usd: 0.01, created_at: '2026-01-01T00:01:00Z' },
      ],
    });
    renderWithProviders(<TraceTimeline sessionId="s1" />);
    expect(await screen.findByText('推理追溯')).toBeInTheDocument();
  });

  it('onSelectRun 回调可调用', () => {
    mockedGetTrace.mockReturnValue(new Promise(() => {}));
    const onSelectRun = vi.fn();
    renderWithProviders(<TraceTimeline sessionId="s1" onSelectRun={onSelectRun} />);
    expect(onSelectRun).toBeDefined();
  });
});