/**
 * 分子对接页面测试
 *
 * 覆盖：
 * 1. 渲染标题和 3 个模式按钮 + SMILES 输入框
 * 2. 切换到 unimol 模式后点击按钮触发 unimolDock
 * 3. hybrid 模式无 target_id 时显示错误
 * 4. 成功后展示对接结果
 * 5. API 失败时显示错误提示
 */
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { screen, fireEvent, waitFor, cleanup } from '@testing-library/react';
import DockingPage from './page';
import { renderWithProviders } from '@/lib/test-utils';

// ===== mock API =====
const mockUnimolDock = vi.fn();
const mockVinaDock = vi.fn();
const mockHybridDock = vi.fn();

vi.mock('@/lib/api', async () => {
  const actual = await vi.importActual<typeof import('@/lib/api')>('@/lib/api');
  return {
    ...actual,
    unimolDock: (...a: any[]) => mockUnimolDock(...a),
    vinaDock: (...a: any[]) => mockVinaDock(...a),
    hybridDock: (...a: any[]) => mockHybridDock(...a),
  };
});

// ===== fixture =====
const DOCKING_FIXTURE = { score: -8.5, mode: 'unimol', smiles: 'CC(=O)Oc1ccccc1C(=O)O' };

describe('DockingPage', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mockUnimolDock.mockResolvedValue(DOCKING_FIXTURE);
    mockVinaDock.mockResolvedValue({ ...DOCKING_FIXTURE, mode: 'vina' });
    mockHybridDock.mockResolvedValue({ ...DOCKING_FIXTURE, mode: 'hybrid' });
  });
  afterEach(() => cleanup());

  it('渲染标题"分子对接"和 3 个模式按钮 + SMILES 输入框', () => {
    renderWithProviders(<DockingPage />);
    expect(screen.getByText('分子对接')).toBeInTheDocument();
    expect(screen.getByText('Hybrid（LLM + 计算）')).toBeInTheDocument();
    expect(screen.getByText('Uni-Mol 粗筛')).toBeInTheDocument();
    expect(screen.getByText('Vina 精修')).toBeInTheDocument();
    expect(screen.getByPlaceholderText(/CC\(=O\)Oc1ccccc1C\(=O\)O/)).toBeInTheDocument();
  });

  it('默认 hybrid 模式显示 Target ID 输入框，切换到 unimol 后 SMILES 输入仍可用', () => {
    renderWithProviders(<DockingPage />);
    // 默认 hybrid 模式显示 TargetSelect 组件（placeholder 文本）
    expect(screen.getByText('选择已发现的靶点（无需手工复制 ID）')).toBeInTheDocument();

    // 切换到 unimol
    fireEvent.click(screen.getByText('Uni-Mol 粗筛'));
    expect(screen.getByPlaceholderText(/CC\(=O\)Oc1ccccc1C\(=O\)O/)).toBeInTheDocument();
  });

  it('unimol 模式输入 SMILES 后点击按钮触发 unimolDock', async () => {
    renderWithProviders(<DockingPage />);
    // 切换到 unimol 模式（无需 target_id）
    fireEvent.click(screen.getByText('Uni-Mol 粗筛'));

    const smilesInput = screen.getByPlaceholderText(/CC\(=O\)Oc1ccccc1C\(=O\)O/);
    fireEvent.change(smilesInput, { target: { value: 'CCO' } });
    fireEvent.click(screen.getByText('开始对接'));

    await waitFor(() => {
      expect(mockUnimolDock).toHaveBeenCalledWith({ smiles: 'CCO', target_name: '' });
    });
  });

  it('hybrid 模式无 target_id 时按钮禁用，不触发对接', () => {
    renderWithProviders(<DockingPage />);
    // 默认 hybrid 模式，不填 target_id
    const smilesInput = screen.getByPlaceholderText(/CC\(=O\)Oc1ccccc1C\(=O\)O/);
    fireEvent.change(smilesInput, { target: { value: 'CCO' } });

    expect(screen.getByText('开始对接')).toBeDisabled();
    expect(mockHybridDock).not.toHaveBeenCalled();
  });

  it('unimol 模式成功后展示对接结果', async () => {
    renderWithProviders(<DockingPage />);
    fireEvent.click(screen.getByText('Uni-Mol 粗筛'));
    fireEvent.change(screen.getByPlaceholderText(/CC\(=O\)Oc1ccccc1C\(=O\)O/), {
      target: { value: 'CCO' },
    });
    fireEvent.click(screen.getByText('开始对接'));

    await waitFor(() => {
      expect(screen.getByText('结合亲和力')).toBeInTheDocument();
    });
  });

  it('API 失败时显示错误提示', async () => {
    mockUnimolDock.mockRejectedValueOnce({
      response: { data: { detail: 'Uni-Mol 引擎超时' } },
    });
    renderWithProviders(<DockingPage />);
    fireEvent.click(screen.getByText('Uni-Mol 粗筛'));
    fireEvent.change(screen.getByPlaceholderText(/CC\(=O\)Oc1ccccc1C\(=O\)O/), {
      target: { value: 'CCO' },
    });
    fireEvent.click(screen.getByText('开始对接'));

    await waitFor(() => {
      expect(screen.getByText('Uni-Mol 引擎超时')).toBeInTheDocument();
    });
  });
});
