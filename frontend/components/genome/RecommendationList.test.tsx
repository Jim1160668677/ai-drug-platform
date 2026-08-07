import { describe, it, expect } from 'vitest';
import { screen } from '@testing-library/react';
import RecommendationList from './RecommendationList';
import { renderWithProviders } from '@/lib/test-utils';

describe('RecommendationList 组件', () => {
  describe('加载与空态', () => {
    it('loading 状态显示 3 个骨架屏', () => {
      const { container } = renderWithProviders(
        <RecommendationList recommendations={[]} loading={true} />
      );
      const skeletons = container.querySelectorAll('.animate-pulse');
      expect(skeletons.length).toBe(3);
    });

    it('空列表显示"暂无生活建议"', () => {
      renderWithProviders(<RecommendationList recommendations={[]} />);
      expect(screen.getByText('暂无生活建议')).toBeInTheDocument();
    });

    it('recommendations 为 undefined 显示"暂无生活建议"', () => {
      renderWithProviders(
        <RecommendationList recommendations={undefined as any} />
      );
      expect(screen.getByText('暂无生活建议')).toBeInTheDocument();
    });
  });

  describe('优先级排序', () => {
    it('按 urgent > high > medium > low 排序', () => {
      renderWithProviders(
        <RecommendationList
          recommendations={[
            { id: '1', content: '低优先级项', priority: 'low' },
            { id: '2', content: '紧急项', priority: 'urgent' },
            { id: '3', content: '中等项', priority: 'medium' },
            { id: '4', content: '高优先级项', priority: 'high' },
          ]}
        />
      );
      const labels = screen.getAllByText(/紧急|高|中|低优先级项|紧急项|中等项|高优先级项/);
      // 优先级标签顺序
      const priorityLabels = screen.getAllByText(/^(紧急|高|中|低)$/);
      expect(priorityLabels[0]).toHaveTextContent('紧急');
      expect(priorityLabels[1]).toHaveTextContent('高');
      expect(priorityLabels[2]).toHaveTextContent('中');
      expect(priorityLabels[3]).toHaveTextContent('低');
    });

    it('未知 priority 回退到 low', () => {
      renderWithProviders(
        <RecommendationList
          recommendations={[
            { id: '1', content: '未知优先级', priority: 'unknown' },
          ]}
        />
      );
      expect(screen.getByText('低')).toBeInTheDocument();
      expect(screen.getByText('未知优先级')).toBeInTheDocument();
    });

    it('priority 缺省视为 low', () => {
      renderWithProviders(
        <RecommendationList
          recommendations={[{ id: '1', content: '无优先级标记' }]}
        />
      );
      expect(screen.getByText('低')).toBeInTheDocument();
    });
  });

  describe('内容渲染', () => {
    it('显示 category 与 evidence', () => {
      renderWithProviders(
        <RecommendationList
          recommendations={[
            {
              id: '1',
              content: '建议每天运动 30 分钟',
              category: '生活方式',
              priority: 'medium',
              evidence: 'GWAS rs1234',
            },
          ]}
        />
      );
      expect(screen.getByText('建议每天运动 30 分钟')).toBeInTheDocument();
      expect(screen.getByText('生活方式')).toBeInTheDocument();
      expect(screen.getByText('依据：GWAS rs1234')).toBeInTheDocument();
    });

    it('无 category 与 evidence 时不渲染对应节点', () => {
      renderWithProviders(
        <RecommendationList
          recommendations={[
            { id: '1', content: '纯内容项', priority: 'low' },
          ]}
        />
      );
      expect(screen.getByText('纯内容项')).toBeInTheDocument();
      expect(screen.queryByText(/依据：/)).not.toBeInTheDocument();
    });

    it('多个建议均渲染', () => {
      renderWithProviders(
        <RecommendationList
          recommendations={[
            { id: '1', content: '建议 A', priority: 'urgent' },
            { id: '2', content: '建议 B', priority: 'high' },
            { id: '3', content: '建议 C', priority: 'medium' },
          ]}
        />
      );
      expect(screen.getByText('建议 A')).toBeInTheDocument();
      expect(screen.getByText('建议 B')).toBeInTheDocument();
      expect(screen.getByText('建议 C')).toBeInTheDocument();
    });

    it('缺少 id 时使用 index 作为 key', () => {
      // 不报错即通过
      renderWithProviders(
        <RecommendationList
          recommendations={[
            { content: '无 id 项 1', priority: 'low' },
            { content: '无 id 项 2', priority: 'low' },
          ]}
        />
      );
      expect(screen.getByText('无 id 项 1')).toBeInTheDocument();
      expect(screen.getByText('无 id 项 2')).toBeInTheDocument();
    });
  });
});
