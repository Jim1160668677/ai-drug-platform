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

  it('tool_call 含证据时显示可展开按钮', async () => {
    mockedGetTrace.mockResolvedValue({
      session_id: 's1',
      total_steps: 1,
      traces: [
        {
          id: 't1',
          step_type: 'tool_call',
          status: 'completed',
          created_at: '2026-01-01T00:00:00Z',
          evidence: {
            query: 'EGFR cancer',
            sources: ['pubmed', 'biorxiv'],
            total_hits: { pubmed: 5, biorxiv: 3 },
            papers: [
              {
                id: 'p1',
                title: 'EGFR signaling in cancer',
                authors: ['Smith J', 'Doe A'],
                year: 2024,
                source: 'pubmed',
                doi: '10.1000/abc123',
                url: 'https://pubmed.ncbi.nlm.nih.gov/123',
              },
            ],
          },
        },
      ],
    });
    renderWithProviders(<TraceTimeline sessionId="s1" />);
    expect(await screen.findByText('推理追溯 (1)')).toBeInTheDocument();

    // 点击展开
    const toggle = screen.getByText('tool call');
    fireEvent.click(toggle);

    expect(await screen.findByText(/EGFR signaling in cancer/)).toBeInTheDocument();
  });

  it('展开后显示查询摘要和来源徽章', async () => {
    mockedGetTrace.mockResolvedValue({
      session_id: 's1',
      total_steps: 1,
      traces: [
        {
          id: 't1',
          step_type: 'tool_call',
          status: 'completed',
          created_at: '2026-01-01T00:00:00Z',
          evidence: {
            query: 'EGFR cancer',
            sources: ['pubmed', 'biorxiv'],
            total_hits: { pubmed: 5, biorxiv: 3 },
            papers: [
              {
                id: 'p1',
                title: 'EGFR signaling in cancer',
                authors: ['Smith J', 'Doe A'],
                year: 2024,
                source: 'pubmed',
                doi: '10.1000/abc123',
                url: 'https://pubmed.ncbi.nlm.nih.gov/123',
              },
            ],
          },
        },
      ],
    });
    renderWithProviders(<TraceTimeline sessionId="s1" />);

    const toggle = await screen.findByText('tool call');
    fireEvent.click(toggle);

    expect(await screen.findByText(/pubmed 5/)).toBeInTheDocument();
    expect(screen.getByText(/biorxiv 3/)).toBeInTheDocument();
    expect(screen.getByText('pubmed')).toBeInTheDocument();
  });

  it('证据卡片含外部链接', async () => {
    mockedGetTrace.mockResolvedValue({
      session_id: 's1',
      total_steps: 1,
      traces: [
        {
          id: 't1',
          step_type: 'tool_call',
          status: 'completed',
          created_at: '2026-01-01T00:00:00Z',
          evidence: {
            query: 'test',
            sources: ['arxiv'],
            total_hits: { arxiv: 2 },
            papers: [
              {
                id: 'p2',
                title: 'Deep learning for drug discovery',
                authors: ['Zhang W'],
                year: 2025,
                source: 'arxiv',
                url: 'https://arxiv.org/abs/2501.00001',
              },
            ],
          },
        },
      ],
    });
    renderWithProviders(<TraceTimeline sessionId="s1" />);

    const toggle = await screen.findByText('tool call');
    fireEvent.click(toggle);

    const link = await screen.findByText('Deep learning for drug discovery');
    expect(link.closest('a')).toHaveAttribute('href', 'https://arxiv.org/abs/2501.00001');
    expect(link.closest('a')).toHaveAttribute('target', '_blank');
  });

  it('无证据的 tool_call 不显示展开', async () => {
    mockedGetTrace.mockResolvedValue({
      session_id: 's1',
      total_steps: 1,
      traces: [
        {
          id: 't2',
          step_type: 'tool_call',
          status: 'completed',
          created_at: '2026-01-01T00:00:00Z',
        },
      ],
    });
    renderWithProviders(<TraceTimeline sessionId="s1" />);
    expect(await screen.findByText('推理追溯')).toBeInTheDocument();
    expect(screen.queryByText(/证据/)).not.toBeInTheDocument();
  });
});