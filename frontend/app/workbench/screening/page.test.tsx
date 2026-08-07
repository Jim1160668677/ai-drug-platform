/**
 * 双上下文筛选页面测试
 *
 * 覆盖：
 * 1. 渲染标题和 2 个模式按钮
 * 2. 默认筛选模式选择靶点后点击按钮触发 dualContextScreen
 * 3. 成功后展示条件放大器高亮
 * 4. 切换到疫苗设计模式，无输入时按钮禁用
 * 5. 疫苗设计模式填入后触发 designVaccine
 * 6. API 失败时显示错误提示
 */
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { screen, fireEvent, waitFor, cleanup } from '@testing-library/react';
import ScreeningPage from './page';
import { renderWithProviders } from '@/lib/test-utils';

// ===== mock API =====
const mockDualContextScreen = vi.fn();
const mockDesignVaccine = vi.fn();
const mockGetTargets = vi.fn();

vi.mock('@/lib/api', async () => {
  const actual = await vi.importActual<typeof import('@/lib/api')>('@/lib/api');
  return {
    ...actual,
    dualContextScreen: (...a: any[]) => mockDualContextScreen(...a),
    designVaccine: (...a: any[]) => mockDesignVaccine(...a),
    getTargets: (...a: any[]) => mockGetTargets(...a),
  };
});

// ===== fixture =====
const TARGETS_FIXTURE = [{ id: 'target-001', gene_symbol: 'EGFR', variant_info: {} }];
const SCREEN_FIXTURE = {
  amplifiers: [{ smiles: 'CCO', score: 0.45 }],
  n_amplifiers: 1,
  n_total: 3,
  summary: 'CCO 在免疫活跃上下文下效应显著增强',
};
const VACCINE_FIXTURE = {
  epitopes: ['MKL', 'KLL'],
  gc_content: 0.52,
  length: 120,
};

describe('ScreeningPage', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mockGetTargets.mockResolvedValue(TARGETS_FIXTURE);
    mockDualContextScreen.mockResolvedValue(SCREEN_FIXTURE);
    mockDesignVaccine.mockResolvedValue(VACCINE_FIXTURE);
  });
  afterEach(() => cleanup());

  it('渲染标题"双上下文筛选 & mRNA 疫苗设计"和 2 个模式按钮', () => {
    renderWithProviders(<ScreeningPage />);
    expect(screen.getByText('双上下文筛选 & mRNA 疫苗设计')).toBeInTheDocument();
    expect(screen.getByText('双上下文筛选')).toBeInTheDocument();
    expect(screen.getByText('mRNA 疫苗设计')).toBeInTheDocument();
  });

  it('默认筛选模式选择靶点后点击"开始筛选"触发 dualContextScreen', async () => {
    renderWithProviders(<ScreeningPage />);
    // 打开 TargetSelect 下拉并选择靶点
    fireEvent.click(screen.getByText('选择已发现的靶点'));
    await waitFor(() => expect(screen.getByText('EGFR')).toBeInTheDocument());
    fireEvent.click(screen.getByText('EGFR'));

    await waitFor(() => {
      expect(screen.getByText('开始筛选')).not.toBeDisabled();
    });
    fireEvent.click(screen.getByText('开始筛选'));

    await waitFor(() => {
      expect(mockDualContextScreen).toHaveBeenCalledWith({
        target_id: 'target-001',
        contexts: ['immune_active', 'neutral'],
      });
    });
  });

  it('筛选成功后展示条件放大器高亮', async () => {
    renderWithProviders(<ScreeningPage />);
    fireEvent.click(screen.getByText('选择已发现的靶点'));
    await waitFor(() => expect(screen.getByText('EGFR')).toBeInTheDocument());
    fireEvent.click(screen.getByText('EGFR'));
    await waitFor(() => {
      expect(screen.getByText('开始筛选')).not.toBeDisabled();
    });
    fireEvent.click(screen.getByText('开始筛选'));

    await waitFor(() => {
      expect(screen.getByText('条件放大器（1 个）')).toBeInTheDocument();
    });
    expect(screen.getByText('CCO 在免疫活跃上下文下效应显著增强')).toBeInTheDocument();
  });

  it('切换到疫苗模式，无输入时按钮禁用不触发', () => {
    renderWithProviders(<ScreeningPage />);
    fireEvent.click(screen.getByText('mRNA 疫苗设计'));

    expect(screen.getByText('设计疫苗')).toBeDisabled();
    expect(mockDesignVaccine).not.toHaveBeenCalled();
  });

  it('疫苗模式填入突变序列后触发 designVaccine', async () => {
    renderWithProviders(<ScreeningPage />);
    fireEvent.click(screen.getByText('mRNA 疫苗设计'));

    const mutationTextarea = screen.getByPlaceholderText('MKWVTIAVLCLAVL...');
    fireEvent.change(mutationTextarea, { target: { value: 'MKKLLLIVTAAH' } });
    fireEvent.click(screen.getByText('设计疫苗'));

    await waitFor(() => {
      expect(mockDesignVaccine).toHaveBeenCalledWith({ sequence: 'MKKLLLIVTAAH' });
    });
  });

  it('dualContextScreen 失败时显示错误提示', async () => {
    mockDualContextScreen.mockRejectedValueOnce({
      response: { data: { detail: '筛选引擎不可用' } },
    });
    renderWithProviders(<ScreeningPage />);
    fireEvent.click(screen.getByText('选择已发现的靶点'));
    await waitFor(() => expect(screen.getByText('EGFR')).toBeInTheDocument());
    fireEvent.click(screen.getByText('EGFR'));
    await waitFor(() => {
      expect(screen.getByText('开始筛选')).not.toBeDisabled();
    });
    fireEvent.click(screen.getByText('开始筛选'));

    await waitFor(() => {
      expect(screen.getByText('筛选引擎不可用')).toBeInTheDocument();
    });
  });
});
