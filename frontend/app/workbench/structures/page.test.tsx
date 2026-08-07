/**
 * 蛋白结构预测页面测试
 *
 * 覆盖：
 * 1. 渲染标题和序列输入框
 * 2. 输入序列后点击按钮触发 predictStructure
 * 3. 成功后展示 pLDDT 分数和 PDB 文本
 * 4. API 失败时显示错误提示
 */
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { screen, fireEvent, waitFor, cleanup } from '@testing-library/react';
import StructuresPage from './page';
import { renderWithProviders } from '@/lib/test-utils';

// ===== mock API =====
const mockPredictStructure = vi.fn();

vi.mock('@/lib/api', async () => {
  const actual = await vi.importActual<typeof import('@/lib/api')>('@/lib/api');
  return {
    ...actual,
    predictStructure: (...a: any[]) => mockPredictStructure(...a),
  };
});

// ===== fixture =====
const STRUCTURE_FIXTURE = {
  structure_id: 'struct-001',
  plddt_mean: 0.85,
  source: 'ESMFold',
  pdb_text: 'ATOM      1  N   MET A   1      11.104  6.134  6.504  1.00  0.00           N',
};

describe('StructuresPage', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mockPredictStructure.mockResolvedValue(STRUCTURE_FIXTURE);
  });
  afterEach(() => cleanup());

  it('渲染标题"蛋白结构预测"和序列输入框', () => {
    renderWithProviders(<StructuresPage />);
    expect(screen.getByText('蛋白结构预测')).toBeInTheDocument();
    expect(screen.getByPlaceholderText(/MKKLLLIVTAAHCLGGSFVGDVNSNE/)).toBeInTheDocument();
    expect(screen.getByText('预测蛋白结构')).toBeInTheDocument();
  });

  it('未输入序列时按钮禁用', () => {
    renderWithProviders(<StructuresPage />);
    const btn = screen.getByText('预测蛋白结构').closest('button');
    expect(btn).toBeDisabled();
  });

  it('输入序列后点击按钮触发 predictStructure', async () => {
    renderWithProviders(<StructuresPage />);
    const input = screen.getByPlaceholderText(/MKKLLLIVTAAHCLGGSFVGDVNSNE/);
    fireEvent.change(input, { target: { value: 'MKKLLLIVTAAHCLGGSFVGDVNSNE' } });

    const btn = screen.getByText('预测蛋白结构').closest('button')!;
    fireEvent.click(btn);

    await waitFor(() => {
      expect(mockPredictStructure).toHaveBeenCalledWith({ sequence: 'MKKLLLIVTAAHCLGGSFVGDVNSNE' });
    });
  });

  it('调用成功后展示 pLDDT 分数和 PDB 文本', async () => {
    renderWithProviders(<StructuresPage />);
    const input = screen.getByPlaceholderText(/MKKLLLIVTAAHCLGGSFVGDVNSNE/);
    fireEvent.change(input, { target: { value: 'MKKLLL' } });
    fireEvent.click(screen.getByText('预测蛋白结构').closest('button')!);

    // 等待结果渲染
    await waitFor(() => {
      expect(screen.getByText('预测结果')).toBeInTheDocument();
    });
    // plddt_mean=0.85 → (0.85 * 100).toFixed(2) + '%' = "85.00%"
    expect(screen.getByText('85.00%')).toBeInTheDocument();
    // 来源
    expect(screen.getByText('ESMFold')).toBeInTheDocument();
    // PDB 文本可展开（文案为"查看 PDB 文本（N 字节）"，用正则匹配）
    expect(screen.getByText(/查看 PDB 文本/)).toBeInTheDocument();
  });

  it('API 失败时显示错误提示', async () => {
    mockPredictStructure.mockRejectedValueOnce({
      response: { data: { detail: 'ESMFold 服务不可用' } },
    });
    renderWithProviders(<StructuresPage />);
    const input = screen.getByPlaceholderText(/MKKLLLIVTAAHCLGGSFVGDVNSNE/);
    fireEvent.change(input, { target: { value: 'MKKLLL' } });
    fireEvent.click(screen.getByText('预测蛋白结构').closest('button')!);

    await waitFor(() => {
      expect(screen.getByText('ESMFold 服务不可用')).toBeInTheDocument();
    });
  });
});
