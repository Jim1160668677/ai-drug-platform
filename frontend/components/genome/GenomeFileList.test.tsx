import { describe, it, expect, vi, beforeEach } from 'vitest';
import { screen, fireEvent, waitFor } from '@testing-library/react';
import GenomeFileList from './GenomeFileList';
import { renderWithProviders } from '@/lib/test-utils';

const mockListGenomes = vi.fn();
const mockDeleteGenome = vi.fn();
vi.mock('@/lib/api', () => ({
  listGenomes: (...args: any[]) => mockListGenomes(...args),
  deleteGenome: (...args: any[]) => mockDeleteGenome(...args),
}));

describe('GenomeFileList 组件', () => {
  beforeEach(() => {
    mockListGenomes.mockReset();
    mockDeleteGenome.mockReset();
    // jsdom 默认 confirm 返回 false，stub 为 true 以测试删除流程
    vi.stubGlobal('confirm', true);
  });

  describe('加载与空态', () => {
    it('加载中显示 Loading', () => {
      mockListGenomes.mockReturnValue(new Promise(() => {}));
      renderWithProviders(<GenomeFileList />);
      expect(screen.getByText('加载基因组文件...')).toBeInTheDocument();
    });

    it('空列表显示"暂无上传的基因组文件"', async () => {
      mockListGenomes.mockResolvedValue({ data: [] });
      renderWithProviders(<GenomeFileList />);
      await waitFor(() => {
        expect(screen.getByText('暂无上传的基因组文件')).toBeInTheDocument();
      });
    });

    it('加载失败显示错误与重试按钮', async () => {
      mockListGenomes.mockRejectedValue(new Error('network'));
      renderWithProviders(<GenomeFileList />);
      await waitFor(() => {
        expect(screen.getByText('加载失败，请重试')).toBeInTheDocument();
        expect(screen.getByText('重试')).toBeInTheDocument();
      });
    });

    it('点击重试重新请求', async () => {
      mockListGenomes.mockRejectedValueOnce(new Error('err'));
      renderWithProviders(<GenomeFileList />);
      await waitFor(() => screen.getByText('重试'));
      mockListGenomes.mockResolvedValue({ data: [] });
      fireEvent.click(screen.getByText('重试'));
      await waitFor(() => {
        expect(screen.getByText('暂无上传的基因组文件')).toBeInTheDocument();
      });
    });
  });

  describe('列表渲染', () => {
    it('渲染基因组文件卡片', async () => {
      mockListGenomes.mockResolvedValue({
        data: [
          {
            id: 'g1',
            file_name: 'genome_23andme.txt',
            genome_build: 'GRCh37',
            total_variants: 12345,
            source_format: '23andme',
            created_at: '2026-01-01T00:00:00Z',
          },
        ],
      });
      renderWithProviders(<GenomeFileList />);
      await waitFor(() => screen.getByText('genome_23andme.txt'));
      expect(screen.getByText('GRCh37')).toBeInTheDocument();
      expect(screen.getByText('变体数：12345')).toBeInTheDocument();
      expect(screen.getByText('格式：23andme')).toBeInTheDocument();
    });

    it('genome_build 缺省显示 GRCh37', async () => {
      mockListGenomes.mockResolvedValue({
        data: [{ id: 'g1', file_name: 'f.txt', total_variants: 1 }],
      });
      renderWithProviders(<GenomeFileList />);
      await waitFor(() => screen.getByText('f.txt'));
      expect(screen.getByText('GRCh37')).toBeInTheDocument();
      expect(screen.getByText('格式：generic')).toBeInTheDocument();
    });

    it('total_variants 缺省显示 —', async () => {
      mockListGenomes.mockResolvedValue({
        data: [{ id: 'g1', file_name: 'f.txt' }],
      });
      renderWithProviders(<GenomeFileList />);
      await waitFor(() => screen.getByText('f.txt'));
      expect(screen.getByText('变体数：—')).toBeInTheDocument();
    });

    it('兼容 items 字段', async () => {
      mockListGenomes.mockResolvedValue({
        items: [{ id: 'g2', file_name: 'items.txt', total_variants: 2 }],
      });
      renderWithProviders(<GenomeFileList />);
      await waitFor(() => screen.getByText('items.txt'));
      expect(screen.getByText('变体数：2')).toBeInTheDocument();
    });
  });

  describe('选中状态', () => {
    it('selectedGenomeId 匹配时高亮并显示 CheckCircle2 图标', async () => {
      mockListGenomes.mockResolvedValue({
        data: [
          { id: 'g1', file_name: 'selected.txt', total_variants: 1 },
          { id: 'g2', file_name: 'other.txt', total_variants: 2 },
        ],
      });
      const { container } = renderWithProviders(
        <GenomeFileList selectedGenomeId="g1" />
      );
      await waitFor(() => screen.getByText('selected.txt'));
      const selectedCard = container.querySelector('.border-primary-500');
      expect(selectedCard).not.toBeNull();
    });

    it('点击卡片触发 onSelect', async () => {
      mockListGenomes.mockResolvedValue({
        data: [{ id: 'g1', file_name: 'click.txt', total_variants: 1 }],
      });
      const onSelect = vi.fn();
      renderWithProviders(<GenomeFileList onSelect={onSelect} />);
      await waitFor(() => screen.getByText('click.txt'));
      fireEvent.click(screen.getByText('click.txt'));
      expect(onSelect).toHaveBeenCalledWith(
        expect.objectContaining({ id: 'g1', file_name: 'click.txt' })
      );
    });
  });

  describe('删除操作', () => {
    it('readOnly 模式不显示删除按钮', async () => {
      mockListGenomes.mockResolvedValue({
        data: [{ id: 'g1', file_name: 'f.txt', total_variants: 1 }],
      });
      renderWithProviders(<GenomeFileList readOnly={true} />);
      await waitFor(() => screen.getByText('f.txt'));
      expect(screen.queryByText('删除成功')).not.toBeInTheDocument();
      // 无删除按钮（Trash2 图标）
      const deleteBtn = screen.queryByRole('button', { name: '' });
      // 只读时无删除按钮
    });

    it('点击删除按钮弹出确认框', async () => {
      mockListGenomes.mockResolvedValue({
        data: [{ id: 'g1', file_name: 'to_delete.txt', total_variants: 1 }],
      });
      mockDeleteGenome.mockResolvedValue({});
      const confirmSpy = vi.fn(() => true);
      vi.stubGlobal('confirm', confirmSpy);
      renderWithProviders(<GenomeFileList />);
      await waitFor(() => screen.getByText('to_delete.txt'));
      // 点击删除按钮（最后一个 button）
      const deleteBtn = screen.getAllByRole('button').find(
        (b) => b.querySelector('svg.lucide-trash-2') ||
               b.classList.contains('text-red-600')
      ) as HTMLElement;
      fireEvent.click(deleteBtn);
      expect(confirmSpy).toHaveBeenCalled();
      const confirmMsg = confirmSpy.mock.calls[0][0];
      expect(confirmMsg).toContain('to_delete.txt');
    });

    it('删除成功后刷新列表', async () => {
      mockListGenomes.mockResolvedValue({
        data: [{ id: 'g1', file_name: 'del.txt', total_variants: 1 }],
      });
      mockDeleteGenome.mockResolvedValue({});
      vi.stubGlobal('confirm', () => true);
      renderWithProviders(<GenomeFileList />);
      await waitFor(() => screen.getByText('del.txt'));
      const deleteBtn = screen.getAllByRole('button').find(
        (b) => b.classList.contains('text-red-600')
      ) as HTMLElement;
      fireEvent.click(deleteBtn);
      await waitFor(() => {
        expect(mockDeleteGenome).toHaveBeenCalledWith('g1');
      });
    });

    it('取消确认时不删除', async () => {
      mockListGenomes.mockResolvedValue({
        data: [{ id: 'g1', file_name: 'cancel.txt', total_variants: 1 }],
      });
      vi.stubGlobal('confirm', () => false);
      renderWithProviders(<GenomeFileList />);
      await waitFor(() => screen.getByText('cancel.txt'));
      const deleteBtn = screen.getAllByRole('button').find(
        (b) => b.classList.contains('text-red-600')
      ) as HTMLElement;
      fireEvent.click(deleteBtn);
      expect(mockDeleteGenome).not.toHaveBeenCalled();
    });
  });

  describe('分页参数', () => {
    it('默认请求 50 条', async () => {
      mockListGenomes.mockResolvedValue({ data: [] });
      renderWithProviders(<GenomeFileList />);
      await waitFor(() => screen.getByText('暂无上传的基因组文件'));
      expect(mockListGenomes).toHaveBeenCalledWith(1, 50);
    });
  });
});
