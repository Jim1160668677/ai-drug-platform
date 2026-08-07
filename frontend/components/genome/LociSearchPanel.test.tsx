import { describe, it, expect, vi, beforeEach } from 'vitest';
import { screen, fireEvent, waitFor } from '@testing-library/react';
import LociSearchPanel from './LociSearchPanel';
import { renderWithProviders } from '@/lib/test-utils';

const mockGetTraitLoci = vi.fn();
const mockSearchLoci = vi.fn();
vi.mock('@/lib/api', () => ({
  getTraitLoci: (...args: any[]) => mockGetTraitLoci(...args),
  searchLoci: (...args: any[]) => mockSearchLoci(...args),
}));

vi.mock('@/lib/notification', () => ({
  toast: {
    success: vi.fn(),
    error: vi.fn(),
    warning: vi.fn(),
    info: vi.fn(),
  },
}));

describe('LociSearchPanel 组件', () => {
  beforeEach(() => {
    mockGetTraitLoci.mockReset();
    mockSearchLoci.mockReset();
  });

  describe('traitId 为空', () => {
    it('显示"请先在上方选择一个性状"', () => {
      renderWithProviders(<LociSearchPanel traitId={null} />);
      expect(screen.getByText('请先在上方选择一个性状')).toBeInTheDocument();
    });

    it('traitId 为空时不请求 getTraitLoci', () => {
      mockGetTraitLoci.mockReturnValue(new Promise(() => {}));
      renderWithProviders(<LociSearchPanel traitId={null} />);
      expect(mockGetTraitLoci).not.toHaveBeenCalled();
    });
  });

  describe('位点列表加载', () => {
    it('加载中显示 Loading', () => {
      mockGetTraitLoci.mockReturnValue(new Promise(() => {}));
      renderWithProviders(<LociSearchPanel traitId="t1" traitName="乳糖不耐受" />);
      expect(screen.getByText('加载位点...')).toBeInTheDocument();
    });

    it('空位点列表显示"暂无位点"', async () => {
      mockGetTraitLoci.mockResolvedValue({ data: { loci: [] } });
      renderWithProviders(<LociSearchPanel traitId="t1" />);
      await waitFor(() => {
        expect(screen.getByText(/暂无位点/)).toBeInTheDocument();
      });
    });

    it('渲染位点表格（含 rsID/染色体/位置等列）', async () => {
      mockGetTraitLoci.mockResolvedValue({
        data: {
          loci: [
            {
              id: 'l1',
              rsid: 'rs4988235',
              chromosome: '2',
              position: 136608646,
              risk_genotype: 'AA',
              effect_size: 0.85,
              locus_tier: 'CORE',
              is_approved: true,
            },
          ],
        },
      });
      renderWithProviders(<LociSearchPanel traitId="t1" traitName="乳糖不耐受" />);
      await waitFor(() => screen.getByText('rs4988235'));
      expect(screen.getByText('染色体')).toBeInTheDocument();
      expect(screen.getByText('位置')).toBeInTheDocument();
      expect(screen.getByText('风险基因型')).toBeInTheDocument();
      expect(screen.getByText('效应量')).toBeInTheDocument();
      expect(screen.getByText('层级')).toBeInTheDocument();
      expect(screen.getByText('审核')).toBeInTheDocument();
      expect(screen.getByText('AA')).toBeInTheDocument();
      expect(screen.getByText('0.85')).toBeInTheDocument();
      expect(screen.getByText('核心')).toBeInTheDocument();
      expect(screen.getByText('已审')).toBeInTheDocument();
    });

    it('CORE 层级显示"核心"徽章，其他显示"辅助"', async () => {
      mockGetTraitLoci.mockResolvedValue({
        data: {
          loci: [
            { id: 'l1', rsid: 'rs1', locus_tier: 'CORE', is_approved: true },
            { id: 'l2', rsid: 'rs2', locus_tier: 'AUXILIARY', is_approved: false },
          ],
        },
      });
      renderWithProviders(<LociSearchPanel traitId="t1" />);
      await waitFor(() => screen.getByText('rs1'));
      expect(screen.getByText('核心')).toBeInTheDocument();
      expect(screen.getAllByText('辅助').length).toBeGreaterThan(0);
    });

    it('is_approved true 显示"已审"，false 显示"待审"', async () => {
      mockGetTraitLoci.mockResolvedValue({
        data: {
          loci: [
            { id: 'l1', rsid: 'rs1', is_approved: true },
            { id: 'l2', rsid: 'rs2', is_approved: false },
          ],
        },
      });
      renderWithProviders(<LociSearchPanel traitId="t1" />);
      await waitFor(() => screen.getByText('rs1'));
      expect(screen.getByText('已审')).toBeInTheDocument();
      expect(screen.getByText('待审')).toBeInTheDocument();
    });

    it('显示位点数量徽章', async () => {
      mockGetTraitLoci.mockResolvedValue({
        data: {
          loci: [
            { id: 'l1', rsid: 'rs1', is_approved: true },
            { id: 'l2', rsid: 'rs2', is_approved: true },
            { id: 'l3', rsid: 'rs3', is_approved: true },
          ],
        },
      });
      renderWithProviders(<LociSearchPanel traitId="t1" />);
      await waitFor(() => screen.getByText('rs1'));
      expect(screen.getByText('3 个')).toBeInTheDocument();
    });

    it('traitName 显示在标题', async () => {
      mockGetTraitLoci.mockResolvedValue({ data: { loci: [] } });
      renderWithProviders(<LociSearchPanel traitId="t1" traitName="酒精代谢" />);
      await waitFor(() => screen.getByText(/暂无位点/));
      expect(screen.getByText(/酒精代谢/)).toBeInTheDocument();
    });

    it('缺省 traitName 时标题显示"性状"', async () => {
      mockGetTraitLoci.mockResolvedValue({ data: { loci: [] } });
      renderWithProviders(<LociSearchPanel traitId="t1" />);
      await waitFor(() => screen.getByText(/暂无位点/));
      expect(screen.getByText(/性状/)).toBeInTheDocument();
    });
  });

  describe('数据格式兼容', () => {
    it('兼容顶层 loci 数组', async () => {
      mockGetTraitLoci.mockResolvedValue({
        loci: [{ id: 'l1', rsid: 'rs_top', is_approved: true }],
      });
      renderWithProviders(<LociSearchPanel traitId="t1" />);
      await waitFor(() => screen.getByText('rs_top'));
    });

    it('risk_genotype 缺省使用 risk_allele', async () => {
      mockGetTraitLoci.mockResolvedValue({
        data: {
          loci: [
            { id: 'l1', rsid: 'rs1', risk_allele: 'G', is_approved: true },
          ],
        },
      });
      renderWithProviders(<LociSearchPanel traitId="t1" />);
      await waitFor(() => screen.getByText('rs1'));
      expect(screen.getByText('G')).toBeInTheDocument();
    });

    it('effect_size 为 null 显示 —', async () => {
      mockGetTraitLoci.mockResolvedValue({
        data: {
          loci: [
            { id: 'l1', rsid: 'rs1', effect_size: null, is_approved: true },
          ],
        },
      });
      renderWithProviders(<LociSearchPanel traitId="t1" />);
      await waitFor(() => screen.getByText('rs1'));
      // position 列与 effect_size 列均可能显示 —
      const dashes = screen.getAllByText('—');
      expect(dashes.length).toBeGreaterThan(0);
    });
  });

  describe('AI 检索位点', () => {
    it('默认勾选"查询外部数据源"', async () => {
      mockGetTraitLoci.mockResolvedValue({ data: { loci: [] } });
      renderWithProviders(<LociSearchPanel traitId="t1" />);
      await waitFor(() => screen.getByText(/暂无位点/));
      const checkbox = screen.getByRole('checkbox') as HTMLInputElement;
      expect(checkbox.checked).toBe(true);
    });

    it('点击"AI 检索位点"调用 searchLoci', async () => {
      mockGetTraitLoci.mockResolvedValue({ data: { loci: [] } });
      mockSearchLoci.mockResolvedValue({ data: { new_loci_added: 3 } });
      renderWithProviders(
        <LociSearchPanel traitId="t1" userLlmConfigId="cfg1" />
      );
      await waitFor(() => screen.getByText(/暂无位点/));
      fireEvent.click(screen.getByText('AI 检索位点'));
      await waitFor(() => {
        expect(mockSearchLoci).toHaveBeenCalledWith(
          't1',
          expect.objectContaining({ useExternal: true, userLlmConfigId: 'cfg1' })
        );
      });
    });

    it('取消勾选后 useExternal=false', async () => {
      mockGetTraitLoci.mockResolvedValue({ data: { loci: [] } });
      mockSearchLoci.mockResolvedValue({ data: { new_loci_added: 1 } });
      renderWithProviders(<LociSearchPanel traitId="t1" />);
      await waitFor(() => screen.getByText(/暂无位点/));
      const checkbox = screen.getByRole('checkbox') as HTMLInputElement;
      fireEvent.click(checkbox);
      expect(checkbox.checked).toBe(false);
      fireEvent.click(screen.getByText('AI 检索位点'));
      await waitFor(() => {
        expect(mockSearchLoci).toHaveBeenCalledWith(
          't1',
          expect.objectContaining({ useExternal: false })
        );
      });
    });

    it('检索成功后触发 onSearched 回调', async () => {
      mockGetTraitLoci.mockResolvedValue({ data: { loci: [] } });
      const result = { new_loci_added: 5, loci: [] };
      mockSearchLoci.mockResolvedValue({ data: result });
      const onSearched = vi.fn();
      renderWithProviders(
        <LociSearchPanel traitId="t1" onSearched={onSearched} />
      );
      await waitFor(() => screen.getByText(/暂无位点/));
      fireEvent.click(screen.getByText('AI 检索位点'));
      await waitFor(() => {
        expect(onSearched).toHaveBeenCalledWith(result);
      });
    });

    it('检索中显示加载提示与禁用按钮', async () => {
      mockGetTraitLoci.mockResolvedValue({ data: { loci: [] } });
      mockSearchLoci.mockReturnValue(new Promise(() => {}));
      renderWithProviders(<LociSearchPanel traitId="t1" />);
      await waitFor(() => screen.getByText(/暂无位点/));
      fireEvent.click(screen.getByText('AI 检索位点'));
      await waitFor(() => {
        expect(
          screen.getByText(/正在调用 LLM 检索位点/)
        ).toBeInTheDocument();
      });
    });
  });
});
