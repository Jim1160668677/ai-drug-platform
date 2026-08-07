import { describe, it, expect } from 'vitest';
import { render, screen } from '@testing-library/react';
import InterpretResultView from './InterpretResultView';
import type { AnalysisInterpretResponse } from '@/types/intelligence';

const mockData: AnalysisInterpretResponse = {
  intent: 'pathway_analysis',
  conclusion: '该基因集富集于 p53 信号通路',
  hypothesis: 'TP53 可能是潜在治疗靶点',
  recommendations: ['验证 TP53 表达', '测试下游效应'],
  key_findings: ['发现 5 个差异基因', '富集评分显著'],
  model: 'agnes-2.0-flash',
  cost_usd: 0.0042,
  duration_sec: 3.5,
};

describe('InterpretResultView', () => {
  it('渲染结论', () => {
    render(<InterpretResultView data={mockData} />);
    expect(screen.getByText('该基因集富集于 p53 信号通路')).toBeInTheDocument();
  });

  it('渲染假设', () => {
    render(<InterpretResultView data={mockData} />);
    expect(screen.getByText('TP53 可能是潜在治疗靶点')).toBeInTheDocument();
  });

  it('渲染关键发现列表', () => {
    render(<InterpretResultView data={mockData} />);
    expect(screen.getByText('发现 5 个差异基因')).toBeInTheDocument();
    expect(screen.getByText('富集评分显著')).toBeInTheDocument();
  });

  it('渲染建议列表（带编号）', () => {
    render(<InterpretResultView data={mockData} />);
    expect(screen.getByText('验证 TP53 表达')).toBeInTheDocument();
    expect(screen.getByText('测试下游效应')).toBeInTheDocument();
  });

  it('显示元信息（模型/成本/耗时）', () => {
    render(<InterpretResultView data={mockData} />);
    expect(screen.getByText('agnes-2.0-flash')).toBeInTheDocument();
    expect(screen.getByText('$0.0042')).toBeInTheDocument();
  });

  it('data 为 null 时显示空状态', () => {
    render(<InterpretResultView data={null as unknown as AnalysisInterpretResponse} />);
    expect(screen.getByText('暂无解读结果')).toBeInTheDocument();
  });
});