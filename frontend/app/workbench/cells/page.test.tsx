/**
 * 单细胞分析页面测试
 *
 * 覆盖：
 * 1. 渲染标题和 3 个 Tab 按钮
 * 2. 基因扰动 Tab 输入基因后触发 predictPerturbation
 * 3. 切换到引擎状态 Tab 触发 listCellEngines
 * 4. 切换到细胞注释 Tab 显示提示文字
 * 5. API 失败时显示错误提示
 */
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { screen, fireEvent, waitFor, cleanup } from '@testing-library/react';
import CellsPage from './page';
import { renderWithProviders } from '@/lib/test-utils';

// ===== mock API =====
const mockPredictPerturbation = vi.fn();
const mockAnnotateCells = vi.fn();
const mockListCellEngines = vi.fn();

vi.mock('@/lib/api', async () => {
  const actual = await vi.importActual<typeof import('@/lib/api')>('@/lib/api');
  return {
    ...actual,
    predictPerturbation: (...a: any[]) => mockPredictPerturbation(...a),
    annotateCells: (...a: any[]) => mockAnnotateCells(...a),
    listCellEngines: (...a: any[]) => mockListCellEngines(...a),
  };
});

// ===== fixture =====
const PERTURBATION_FIXTURE = { gene: 'EGFR', effect: 'downregulated', confidence: 0.92 };
const ENGINES_FIXTURE = { engines: [{ name: 'scGPT', status: 'ready' }] };

describe('CellsPage', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mockPredictPerturbation.mockResolvedValue(PERTURBATION_FIXTURE);
    mockListCellEngines.mockResolvedValue(ENGINES_FIXTURE);
  });
  afterEach(() => cleanup());

  it('渲染标题"单细胞分析"和 3 个 Tab 按钮', () => {
    renderWithProviders(<CellsPage />);
    expect(screen.getByText('单细胞分析')).toBeInTheDocument();
    expect(screen.getByText('基因扰动')).toBeInTheDocument();
    expect(screen.getByText('细胞注释')).toBeInTheDocument();
    expect(screen.getByText('引擎状态')).toBeInTheDocument();
  });

  it('默认基因扰动 Tab 显示基因符号输入框和"预测扰动效应"按钮', () => {
    renderWithProviders(<CellsPage />);
    expect(screen.getByPlaceholderText(/EGFR/)).toBeInTheDocument();
    expect(screen.getByText(/预测扰动效应/)).toBeInTheDocument();
  });

  it('输入基因符号后点击按钮触发 predictPerturbation', async () => {
    renderWithProviders(<CellsPage />);
    const input = screen.getByPlaceholderText(/EGFR/);
    fireEvent.change(input, { target: { value: 'EGFR' } });
    fireEvent.click(screen.getByText(/预测扰动效应/));

    await waitFor(() => {
      expect(mockPredictPerturbation).toHaveBeenCalledWith({ gene: 'EGFR' });
    });
  });

  it('切换到引擎状态 Tab 点击按钮触发 listCellEngines', async () => {
    renderWithProviders(<CellsPage />);
    fireEvent.click(screen.getByText('引擎状态'));
    fireEvent.click(screen.getByText('查询引擎状态'));

    await waitFor(() => {
      expect(mockListCellEngines).toHaveBeenCalled();
    });
  });

  it('切换到细胞注释 Tab 显示提示文字', () => {
    renderWithProviders(<CellsPage />);
    fireEvent.click(screen.getByText('细胞注释'));
    expect(screen.getByText(/细胞注释需上传表达矩阵数据/)).toBeInTheDocument();
  });

  it('predictPerturbation 失败时显示错误提示', async () => {
    mockPredictPerturbation.mockRejectedValueOnce({
      response: { data: { detail: 'scGPT 模型加载失败' } },
    });
    renderWithProviders(<CellsPage />);
    fireEvent.change(screen.getByPlaceholderText(/EGFR/), { target: { value: 'EGFR' } });
    fireEvent.click(screen.getByText(/预测扰动效应/));

    await waitFor(() => {
      expect(screen.getByText('scGPT 模型加载失败')).toBeInTheDocument();
    });
  });
});
