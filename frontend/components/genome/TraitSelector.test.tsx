import { describe, it, expect, vi, beforeEach } from 'vitest';
import { screen, fireEvent, waitFor } from '@testing-library/react';
import TraitSelector from './TraitSelector';
import { renderWithProviders } from '@/lib/test-utils';

// mock genome API
const mockListTraits = vi.fn();
vi.mock('@/lib/api', () => ({
  listTraits: (...args: any[]) => mockListTraits(...args),
}));

describe('TraitSelector 组件', () => {
  beforeEach(() => {
    mockListTraits.mockReset();
  });

  describe('加载与空态', () => {
    it('加载中显示 Loading', async () => {
      // 永不 resolve，保持 loading
      mockListTraits.mockReturnValue(new Promise(() => {}));
      renderWithProviders(
        <TraitSelector selectedTraitIds={[]} onChange={() => {}} />
      );
      expect(screen.getByText('加载性状列表...')).toBeInTheDocument();
    });

    it('空列表显示"暂无可选性状"', async () => {
      mockListTraits.mockResolvedValue({ data: [] });
      renderWithProviders(
        <TraitSelector selectedTraitIds={[]} onChange={() => {}} />
      );
      await waitFor(() => {
        expect(screen.getByText('暂无可选性状')).toBeInTheDocument();
      });
    });

    it('加载失败显示错误与重试按钮', async () => {
      mockListTraits.mockRejectedValue(new Error('network error'));
      renderWithProviders(
        <TraitSelector selectedTraitIds={[]} onChange={() => {}} />
      );
      await waitFor(() => {
        expect(screen.getByText('加载失败')).toBeInTheDocument();
        expect(screen.getByText('重试')).toBeInTheDocument();
      });
    });

    it('点击重试重新请求', async () => {
      mockListTraits.mockRejectedValueOnce(new Error('error'));
      renderWithProviders(
        <TraitSelector selectedTraitIds={[]} onChange={() => {}} />
      );
      await waitFor(() => screen.getByText('重试'));
      mockListTraits.mockResolvedValue({ data: [] });
      fireEvent.click(screen.getByText('重试'));
      await waitFor(() => {
        expect(screen.getByText('暂无可选性状')).toBeInTheDocument();
      });
    });
  });

  describe('性状列表展示与分组', () => {
    it('按 category 分组并显示中文标签', async () => {
      mockListTraits.mockResolvedValue({
        data: [
          { id: 't1', name: '乳糖不耐受', category: 'metabolism' },
          { id: 't2', name: '咖啡因代谢', category: 'metabolism' },
          { id: 't3', name: '高原适应能力', category: 'altitude' },
        ],
      });
      renderWithProviders(
        <TraitSelector selectedTraitIds={[]} onChange={() => {}} />
      );
      await waitFor(() => screen.getByText('乳糖不耐受'));
      expect(screen.getByText('代谢能力')).toBeInTheDocument();
      expect(screen.getByText('高原适应')).toBeInTheDocument(); // category label
      // 分组数量标签
      expect(screen.getByText('2 项')).toBeInTheDocument();
      expect(screen.getByText('1 项')).toBeInTheDocument();
    });

    it('未知 category 显示原值', async () => {
      mockListTraits.mockResolvedValue({
        data: [{ id: 't1', name: '未知类别性状', category: 'custom_cat' }],
      });
      renderWithProviders(
        <TraitSelector selectedTraitIds={[]} onChange={() => {}} />
      );
      await waitFor(() => screen.getByText('未知类别性状'));
      expect(screen.getByText('custom_cat')).toBeInTheDocument();
    });

    it('无 category 归到 other 分组', async () => {
      mockListTraits.mockResolvedValue({
        data: [{ id: 't1', name: '无类别性状' }],
      });
      renderWithProviders(
        <TraitSelector selectedTraitIds={[]} onChange={() => {}} />
      );
      await waitFor(() => screen.getByText('无类别性状'));
      expect(screen.getByText('other')).toBeInTheDocument();
    });

    it('显示性状描述', async () => {
      mockListTraits.mockResolvedValue({
        data: [
          { id: 't1', name: '酒精代谢', description: 'ALDH2 基因相关', category: 'metabolism' },
        ],
      });
      renderWithProviders(
        <TraitSelector selectedTraitIds={[]} onChange={() => {}} />
      );
      await waitFor(() => screen.getByText('酒精代谢'));
      expect(screen.getByText('ALDH2 基因相关')).toBeInTheDocument();
    });
  });

  describe('选中状态与回调', () => {
    it('点击未选中性状触发 onChange 添加', async () => {
      mockListTraits.mockResolvedValue({
        data: [{ id: 't1', name: '性状 A', category: 'metabolism' }],
      });
      const onChange = vi.fn();
      renderWithProviders(
        <TraitSelector selectedTraitIds={[]} onChange={onChange} />
      );
      await waitFor(() => screen.getByText('性状 A'));
      fireEvent.click(screen.getByText('性状 A'));
      expect(onChange).toHaveBeenCalledWith(['t1']);
    });

    it('点击已选中性状触发 onChange 移除', async () => {
      mockListTraits.mockResolvedValue({
        data: [{ id: 't1', name: '性状 A', category: 'metabolism' }],
      });
      const onChange = vi.fn();
      renderWithProviders(
        <TraitSelector selectedTraitIds={['t1']} onChange={onChange} />
      );
      await waitFor(() => screen.getByText('性状 A'));
      fireEvent.click(screen.getByText('性状 A'));
      expect(onChange).toHaveBeenCalledWith([]);
    });

    it('已选中的性状显示 CheckCircle2 与选中样式', async () => {
      mockListTraits.mockResolvedValue({
        data: [
          { id: 't1', name: '已选中', category: 'metabolism' },
          { id: 't2', name: '未选中', category: 'metabolism' },
        ],
      });
      const { container } = renderWithProviders(
        <TraitSelector selectedTraitIds={['t1']} onChange={() => {}} />
      );
      await waitFor(() => screen.getByText('已选中'));
      // 选中卡片有 ring-primary-100 类
      const selectedCard = container.querySelector('.ring-primary-100');
      expect(selectedCard).not.toBeNull();
    });

    it('多选时累加 id', async () => {
      mockListTraits.mockResolvedValue({
        data: [
          { id: 't1', name: 'A', category: 'metabolism' },
          { id: 't2', name: 'B', category: 'metabolism' },
        ],
      });
      const onChange = vi.fn();
      renderWithProviders(
        <TraitSelector selectedTraitIds={['t1']} onChange={onChange} />
      );
      await waitFor(() => screen.getByText('A'));
      fireEvent.click(screen.getByText('B'));
      expect(onChange).toHaveBeenCalledWith(['t1', 't2']);
    });
  });

  describe('category 过滤参数', () => {
    it('传入 category 时传给 listTraits', async () => {
      mockListTraits.mockResolvedValue({ data: [] });
      renderWithProviders(
        <TraitSelector
          selectedTraitIds={[]}
          onChange={() => {}}
          category="cardio"
        />
      );
      await waitFor(() => screen.getByText('暂无可选性状'));
      expect(mockListTraits).toHaveBeenCalledWith('cardio', 1, 100);
    });

    it('未传 category 时传 undefined', async () => {
      mockListTraits.mockResolvedValue({ data: [] });
      renderWithProviders(
        <TraitSelector selectedTraitIds={[]} onChange={() => {}} />
      );
      await waitFor(() => screen.getByText('暂无可选性状'));
      expect(mockListTraits).toHaveBeenCalledWith(undefined, 1, 100);
    });
  });

  describe('数据格式兼容', () => {
    it('兼容 items 字段', async () => {
      mockListTraits.mockResolvedValue({
        items: [{ id: 't1', name: 'items 字段性状', category: 'metabolism' }],
      });
      renderWithProviders(
        <TraitSelector selectedTraitIds={[]} onChange={() => {}} />
      );
      await waitFor(() => screen.getByText('items 字段性状'));
    });
  });
});
