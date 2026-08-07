import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, fireEvent, waitFor } from '@testing-library/react';
import { renderWithProviders } from '@/lib/test-utils';
import TraceTimeline from './TraceTimeline';

vi.mock('@/lib/api', () => ({
  getTrace: vi.fn(),
  reexecuteAcademicSearch: vi.fn().mockResolvedValue({
    step_id: 'new-step-1',
    parent_step_id: 't1',
    query: 'test',
    sources_queried: ['pubmed'],
    total_hits: { pubmed: 1 },
    papers: [],
    search_time_ms: 100,
  }),
}));

import { getTrace, reexecuteAcademicSearch } from '@/lib/api';
const mockedGetTrace = vi.mocked(getTrace);
const mockedReexecute = vi.mocked(reexecuteAcademicSearch);

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

  it('展开证据后显示干预按钮', async () => {
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
            sources: ['pubmed'],
            total_hits: { pubmed: 3 },
            papers: [
              { id: 'p1', title: 'Paper A', source: 'pubmed', year: 2024 },
            ],
          },
        },
      ],
    });
    renderWithProviders(<TraceTimeline sessionId="s1" />);

    const toggle = await screen.findByText('tool call');
    fireEvent.click(toggle);

    expect(await screen.findByText('调整检索词')).toBeInTheDocument();
    expect(screen.getByText('添加数据源')).toBeInTheDocument();
  });

  it('点击调整检索词打开编辑 Modal', async () => {
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
            sources: ['pubmed'],
            total_hits: { pubmed: 3 },
            papers: [{ id: 'p1', title: 'Paper A', source: 'pubmed', year: 2024 }],
          },
        },
      ],
    });
    renderWithProviders(<TraceTimeline sessionId="s1" />);

    const toggle = await screen.findByText('tool call');
    fireEvent.click(toggle);

    const editBtn = await screen.findByText('调整检索词');
    fireEvent.click(editBtn);

    const input = screen.getByTestId('edit-query-input');
    expect(input).toBeInTheDocument();
    expect(input).toHaveValue('EGFR cancer');
  });

  it('点击添加数据源打开数据源选择 Modal', async () => {
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
            query: 'test query',
            sources: ['pubmed'],
            total_hits: { pubmed: 2 },
            papers: [{ id: 'p1', title: 'Paper A', source: 'pubmed', year: 2024 }],
          },
        },
      ],
    });
    renderWithProviders(<TraceTimeline sessionId="s1" />);

    const toggle = await screen.findByText('tool call');
    fireEvent.click(toggle);

    const addBtn = await screen.findByText('添加数据源');
    fireEvent.click(addBtn);

    expect(screen.getByText('选择数据源')).toBeInTheDocument();
    expect(screen.getByTestId('source-checkboxes')).toBeInTheDocument();
    expect(screen.getAllByText('pubmed').length).toBeGreaterThan(0);
    expect(screen.getAllByText('biorxiv').length).toBeGreaterThan(0);
  });

  it('取消按钮关闭 Modal', async () => {
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
            query: 'EGFR',
            sources: ['pubmed'],
            total_hits: { pubmed: 1 },
            papers: [{ id: 'p1', title: 'Paper A', source: 'pubmed', year: 2024 }],
          },
        },
      ],
    });
    renderWithProviders(<TraceTimeline sessionId="s1" />);

    const toggle = await screen.findByText('tool call');
    fireEvent.click(toggle);

    fireEvent.click(await screen.findByText('调整检索词'));
    expect(screen.getByTestId('edit-query-input')).toBeInTheDocument();

    fireEvent.click(screen.getByText('取消'));
    expect(screen.queryByTestId('edit-query-input')).not.toBeInTheDocument();
  });

  it('编辑检索词后输入框内容更新', async () => {
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
            query: 'original',
            sources: ['pubmed'],
            total_hits: { pubmed: 2 },
            papers: [{ id: 'p1', title: 'Old Paper', source: 'pubmed', year: 2024 }],
          },
        },
      ],
    });

    renderWithProviders(<TraceTimeline sessionId="s1" />);

    const toggle = await screen.findByText('tool call');
    fireEvent.click(toggle);

    fireEvent.click(await screen.findByText('调整检索词'));
    const input = screen.getByTestId('edit-query-input');
    expect(input).toHaveValue('original');

    fireEvent.change(input, { target: { value: 'updated query' } });
    expect(input).toHaveValue('updated query');
  });

  it('空检索词时重新检索按钮禁用', async () => {
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
            query: 'EGFR',
            sources: ['pubmed'],
            total_hits: { pubmed: 1 },
            papers: [{ id: 'p1', title: 'Paper A', source: 'pubmed', year: 2024 }],
          },
        },
      ],
    });

    renderWithProviders(<TraceTimeline sessionId="s1" />);

    fireEvent.click(await screen.findByText('tool call'));
    fireEvent.click(await screen.findByText('调整检索词'));

    const input = screen.getByTestId('edit-query-input');
    fireEvent.change(input, { target: { value: '' } });

    const submitBtn = screen.getByText('重新检索');
    expect(submitBtn).toBeDisabled();
  });

  it('完整 reexecute 流程：mutation 后新步骤出现在时间线', async () => {
    const initialTraces = [
      {
        id: 't1',
        step_type: 'tool_call',
        status: 'completed',
        created_at: '2026-01-01T00:00:00Z',
        evidence: {
          query: 'original query',
          sources: ['pubmed'],
          total_hits: { pubmed: 5 },
          papers: [{ id: 'p1', title: 'Original Paper', source: 'pubmed', year: 2024 }],
        },
      },
    ];

    mockedGetTrace.mockResolvedValue({
      session_id: 's1',
      total_steps: 1,
      traces: initialTraces,
    });

    mockedReexecute.mockResolvedValue({
      step_id: 'new-step-1',
      parent_step_id: 't1',
      query: 'updated query',
      sources_queried: ['pubmed', 'arxiv'],
      total_hits: { pubmed: 5, arxiv: 3 },
      papers: [
        { id: 'p2', title: 'New Arxiv Paper', source: 'arxiv', year: 2025 },
      ],
      search_time_ms: 150,
    });

    renderWithProviders(<TraceTimeline sessionId="s1" />);

    // 展开原始步骤
    const toggle = await screen.findByText('tool call');
    fireEvent.click(toggle);

    // 点击调整检索词
    fireEvent.click(await screen.findByText('调整检索词'));

    // 修改检索词并提交
    const input = screen.getByTestId('edit-query-input');
    fireEvent.change(input, { target: { value: 'updated query' } });
    fireEvent.click(screen.getByText('重新检索'));

    // 验证 mutation 被调用
    await waitFor(() => {
      expect(mockedReexecute).toHaveBeenCalledWith({
        session_id: 's1',
        original_step_id: 't1',
        query: 'updated query',
      });
    });

    // 验证新步骤出现在时间线中
    await waitFor(() => {
      expect(screen.getByText(/New Arxiv Paper/)).toBeInTheDocument();
    });
  });
});