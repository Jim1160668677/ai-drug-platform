import { describe, it, expect } from 'vitest';
import { render, screen } from '@testing-library/react';
import EvidenceResultView from './EvidenceResultView';
import type { EvidenceResponse } from '@/types/intelligence';

const mockData: EvidenceResponse = {
  text: '这是证据文本',
  sources: [
    { source_type: 'dataset', count: 5, detail: '5 个数据集' },
    { source_type: 'target', count: 3, detail: '3 个靶点' },
  ],
  total_items: 8,
  project_id: 'proj-123',
  entity_id: 'ent-456',
  trigger_event: 'target_discovery',
};

describe('EvidenceResultView', () => {
  it('渲染证据文本', () => {
    render(<EvidenceResultView data={mockData} />);
    expect(screen.getByText('这是证据文本')).toBeInTheDocument();
  });

  it('显示总数', () => {
    render(<EvidenceResultView data={mockData} />);
    expect(screen.getByText('8 项')).toBeInTheDocument();
  });

  it('渲染来源列表', () => {
    render(<EvidenceResultView data={mockData} />);
    expect(screen.getByText('dataset')).toBeInTheDocument();
    expect(screen.getByText('target')).toBeInTheDocument();
    expect(screen.getByText('5')).toBeInTheDocument();
    expect(screen.getByText('3')).toBeInTheDocument();
  });

  it('显示元信息标签', () => {
    render(<EvidenceResultView data={mockData} />);
    expect(screen.getByText(/proj-123/)).toBeInTheDocument();
    expect(screen.getByText(/ent-456/)).toBeInTheDocument();
  });

  it('data 为 null 时显示空状态', () => {
    render(<EvidenceResultView data={null as unknown as EvidenceResponse} />);
    expect(screen.getByText('暂无证据数据')).toBeInTheDocument();
  });

  it('空来源列表不崩溃', () => {
    render(<EvidenceResultView data={{ text: '仅文本', sources: [], total_items: 0 }} />);
    expect(screen.getByText('仅文本')).toBeInTheDocument();
  });
});