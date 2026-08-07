/**
 * 合成规划页面测试
 *
 * 覆盖：
 * 1. 渲染标题"合成规划"和默认 SMILES（阿司匹林）
 * 2. 点击"生成合成规划"按钮触发 planSynthesis
 * 3. 成功后展示可行性评估卡片
 * 4. 成功后展示成本估算和成本分解
 * 5. 成功后展示合成路线
 * 6. API 失败时显示错误提示
 */
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { screen, fireEvent, waitFor, cleanup } from '@testing-library/react';
import SynthesisPage from './page';
import { renderWithProviders } from '@/lib/test-utils';

// ===== mock API =====
const mockPlanSynthesis = vi.fn();

vi.mock('@/lib/api', async () => {
  const actual = await vi.importActual<typeof import('@/lib/api')>('@/lib/api');
  return {
    ...actual,
    planSynthesis: (...a: any[]) => mockPlanSynthesis(...a),
  };
});

// ===== fixture =====
const SYNTHESIS_FIXTURE = {
  feasibility_label: 'easy',
  sa_score: 2.5,
  sc_score: 2.8,
  total_cost_usd: 125.5,
  cost_per_gram: 12.55,
  cost_breakdown: {
    materials: 50.0,
    labor: 30.0,
    equipment: 25.0,
    overhead: 20.0,
    target_scale_grams: 10,
  },
  is_cost_effective: true,
  n_routes: 2,
  routes: [
    {
      n_steps: 3,
      steps: [
        { step: 1, reaction: '酯化反应' },
        { step: 2, reaction: '水解反应' },
        { step: 3, reaction: '纯化' },
      ],
    },
  ],
  recommendation: '推荐路线 1：3 步合成，成本最低',
  risk_assessment: '注意温度控制',
};

describe('SynthesisPage', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mockPlanSynthesis.mockResolvedValue(SYNTHESIS_FIXTURE);
  });
  afterEach(() => cleanup());

  it('渲染标题"合成规划"和默认 SMILES（阿司匹林）', () => {
    renderWithProviders(<SynthesisPage />);
    expect(screen.getByText('合成规划')).toBeInTheDocument();
    // 默认 SMILES 是阿司匹林 CC(=O)Oc1ccccc1C(=O)O
    const smilesInput = screen.getByDisplayValue('CC(=O)Oc1ccccc1C(=O)O');
    expect(smilesInput).toBeInTheDocument();
    expect(screen.getByText('生成合成规划')).toBeInTheDocument();
  });

  it('点击"生成合成规划"按钮触发 planSynthesis', async () => {
    renderWithProviders(<SynthesisPage />);
    fireEvent.click(screen.getByText('生成合成规划'));

    await waitFor(() => {
      expect(mockPlanSynthesis).toHaveBeenCalled();
    });
    const callArgs = mockPlanSynthesis.mock.calls[0][0];
    expect(callArgs.smiles).toBe('CC(=O)Oc1ccccc1C(=O)O');
    expect(callArgs.max_routes).toBe(5);
    expect(callArgs.target_scale_grams).toBe(10);
  });

  it('成功后展示可行性评估卡片', async () => {
    renderWithProviders(<SynthesisPage />);
    fireEvent.click(screen.getByText('生成合成规划'));

    await waitFor(() => {
      expect(screen.getByText('可行性评估')).toBeInTheDocument();
    });
    // SAscore 显示
    expect(screen.getByText(/SAscore:/)).toBeInTheDocument();
  });

  it('成功后展示成本估算和成本分解', async () => {
    renderWithProviders(<SynthesisPage />);
    fireEvent.click(screen.getByText('生成合成规划'));

    await waitFor(() => {
      expect(screen.getByText(/成本估算/)).toBeInTheDocument();
    });
    expect(screen.getByText('总成本')).toBeInTheDocument();
    expect(screen.getByText('单克成本')).toBeInTheDocument();
    // 成本分解项
    expect(screen.getByText('materials')).toBeInTheDocument();
    expect(screen.getByText('labor')).toBeInTheDocument();
    expect(screen.getByText('equipment')).toBeInTheDocument();
    expect(screen.getByText('overhead')).toBeInTheDocument();
  });

  it('成功后展示合成路线', async () => {
    renderWithProviders(<SynthesisPage />);
    fireEvent.click(screen.getByText('生成合成规划'));

    await waitFor(() => {
      expect(screen.getByText(/合成路线/)).toBeInTheDocument();
    });
    // 路线步骤
    expect(screen.getByText('酯化反应')).toBeInTheDocument();
    expect(screen.getByText('水解反应')).toBeInTheDocument();
  });

  it('成功后展示 AI 合成推荐', async () => {
    renderWithProviders(<SynthesisPage />);
    fireEvent.click(screen.getByText('生成合成规划'));

    await waitFor(() => {
      expect(screen.getByText('AI 合成推荐')).toBeInTheDocument();
    });
    expect(screen.getByText('推荐路线 1：3 步合成，成本最低')).toBeInTheDocument();
  });

  it('API 失败时显示错误提示', async () => {
    mockPlanSynthesis.mockRejectedValueOnce({
      response: { data: { detail: 'AiZynthFinder 引擎不可用' } },
    });
    renderWithProviders(<SynthesisPage />);
    fireEvent.click(screen.getByText('生成合成规划'));

    await waitFor(() => {
      expect(screen.getByText('AiZynthFinder 引擎不可用')).toBeInTheDocument();
    });
  });
});
