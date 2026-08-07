import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen } from '@testing-library/react';
import { renderWithProviders } from '@/lib/test-utils';

vi.mock('reactflow', () => ({
  default: ({ children }: { children?: React.ReactNode }) => <div data-testid="mock-reactflow">{children}</div>,
  Background: () => null,
  Controls: () => null,
  Handle: () => null,
  Position: { Top: 'top', Bottom: 'bottom', Left: 'left', Right: 'right' },
}));

vi.mock('dagre', () => {
  const FakeGraph = class {
    setNode() {}
    setEdge() {}
    setGraph() {}
    setDefaultEdgeLabel() {}
    node() { return { x: 0, y: 0 }; }
  };
  return {
    default: { graphlib: { Graph: FakeGraph }, layout: () => {} },
    graphlib: { Graph: FakeGraph },
    layout: () => {},
  };
});

vi.mock('@/lib/api', () => ({
  getTraceTree: vi.fn(),
}));

import { getTraceTree } from '@/lib/api';
const mockedGetTraceTree = vi.mocked(getTraceTree);
import TraceTreeView from './TraceTreeView';

beforeEach(() => {
  vi.clearAllMocks();
});

describe('TraceTreeView', () => {
  it('加载中显示提示', () => {
    mockedGetTraceTree.mockReturnValue(new Promise(() => {}));
    renderWithProviders(<TraceTreeView runId="r1" />);
    expect(screen.getByText('步骤树')).toBeInTheDocument();
  });

  it('空数据显示空状态', async () => {
    mockedGetTraceTree.mockResolvedValue({ roots: [], total_steps: 0, total_cost: 0 });
    renderWithProviders(<TraceTreeView runId="r1" />);
    expect(await screen.findByText('暂无步骤树数据')).toBeInTheDocument();
  });

  it('渲染树不崩溃', async () => {
    mockedGetTraceTree.mockResolvedValue({
      roots: [
        {
          step_id: 's1', step_type: 'user_message', agent_name: null,
          parent_step_id: null, cost_usd: 0, status: 'completed',
          children: [
            { step_id: 's2', step_type: 'llm_call', agent_name: 'agnes', parent_step_id: 's1', cost_usd: 0.01, status: 'completed' },
          ],
        },
      ],
      total_steps: 2, total_cost: 0.01,
    });
    renderWithProviders(<TraceTreeView runId="r1" />);
    expect(await screen.findByTestId('mock-reactflow')).toBeInTheDocument();
  });
});