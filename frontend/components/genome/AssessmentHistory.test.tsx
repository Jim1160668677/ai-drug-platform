import { describe, it, expect, vi, beforeEach } from 'vitest';
import { screen, fireEvent, waitFor } from '@testing-library/react';
import AssessmentHistory from './AssessmentHistory';
import { renderWithProviders } from '@/lib/test-utils';

const mockListAssessments = vi.fn();
vi.mock('@/lib/api', () => ({
  listAssessments: (...args: any[]) => mockListAssessments(...args),
}));

describe('AssessmentHistory 组件', () => {
  beforeEach(() => {
    mockListAssessments.mockReset();
  });

  describe('genomeId 为空', () => {
    it('不渲染内容（enabled=false）', () => {
      mockListAssessments.mockReturnValue(new Promise(() => {}));
      const { container } = renderWithProviders(
        <AssessmentHistory genomeId={null} />
      );
      // query enabled=false，仍渲染标题但无 loading
      expect(screen.getByText('历史评估')).toBeInTheDocument();
      expect(mockListAssessments).not.toHaveBeenCalled();
    });
  });

  describe('加载与空态', () => {
    it('加载中显示 Loading', () => {
      mockListAssessments.mockReturnValue(new Promise(() => {}));
      renderWithProviders(<AssessmentHistory genomeId="g1" />);
      expect(screen.getByText('加载历史评估...')).toBeInTheDocument();
    });

    it('空列表显示"暂无历史评估"', async () => {
      mockListAssessments.mockResolvedValue({ data: { assessments: [] } });
      renderWithProviders(<AssessmentHistory genomeId="g1" />);
      await waitFor(() => {
        expect(screen.getByText('暂无历史评估')).toBeInTheDocument();
      });
    });

    it('assessments 为 undefined 显示空态', async () => {
      mockListAssessments.mockResolvedValue({ data: {} });
      renderWithProviders(<AssessmentHistory genomeId="g1" />);
      await waitFor(() => {
        expect(screen.getByText('暂无历史评估')).toBeInTheDocument();
      });
    });
  });

  describe('评估列表渲染', () => {
    const sampleAssessments = [
      {
        id: 'a1',
        risk_level: 'LOW',
        overall_risk_score: 0.12,
        core_loci_matched: 2,
        auxiliary_loci_matched: 5,
        created_at: '2026-01-15T10:30:00Z',
      },
      {
        id: 'a2',
        risk_level: 'VERY_HIGH',
        overall_risk_score: 0.85,
        core_loci_matched: 8,
        auxiliary_loci_matched: 3,
        created_at: '2026-02-20T08:00:00Z',
      },
    ];

    it('渲染中文风险标签', async () => {
      mockListAssessments.mockResolvedValue({
        data: { assessments: sampleAssessments },
      });
      renderWithProviders(<AssessmentHistory genomeId="g1" />);
      await waitFor(() => screen.getByText('低风险'));
      expect(screen.getByText('极高风险')).toBeInTheDocument();
    });

    it('显示风险评分百分比', async () => {
      mockListAssessments.mockResolvedValue({
        data: { assessments: sampleAssessments },
      });
      renderWithProviders(<AssessmentHistory genomeId="g1" />);
      await waitFor(() => screen.getByText('低风险'));
      expect(screen.getByText('12.0%')).toBeInTheDocument();
      expect(screen.getByText('85.0%')).toBeInTheDocument();
    });

    it('显示核心/辅助位点数', async () => {
      mockListAssessments.mockResolvedValue({
        data: { assessments: [sampleAssessments[0]] },
      });
      renderWithProviders(<AssessmentHistory genomeId="g1" />);
      await waitFor(() => screen.getByText('低风险'));
      expect(screen.getByText('核心位点：')).toBeInTheDocument();
      // 核心位点 2
      const strongElements = document.querySelectorAll('strong');
      const texts = Array.from(strongElements).map((s) => s.textContent);
      expect(texts).toContain('2');
      expect(texts).toContain('5');
    });

    it('未知 risk_level 显示原值', async () => {
      mockListAssessments.mockResolvedValue({
        data: {
          assessments: [
            { id: 'a1', risk_level: 'CUSTOM', overall_risk_score: 0.3, core_loci_matched: 0, auxiliary_loci_matched: 0 },
          ],
        },
      });
      renderWithProviders(<AssessmentHistory genomeId="g1" />);
      await waitFor(() => screen.getByText('CUSTOM'));
    });

    it('overall_risk_score 缺省为 0.0%', async () => {
      mockListAssessments.mockResolvedValue({
        data: {
          assessments: [{ id: 'a1', risk_level: 'LOW', core_loci_matched: 0, auxiliary_loci_matched: 0 }],
        },
      });
      renderWithProviders(<AssessmentHistory genomeId="g1" />);
      await waitFor(() => screen.getByText('低风险'));
      expect(screen.getByText('0.0%')).toBeInTheDocument();
    });

    it('created_at 缺省不渲染日期', async () => {
      mockListAssessments.mockResolvedValue({
        data: {
          assessments: [{ id: 'a1', risk_level: 'LOW', overall_risk_score: 0.1 }],
        },
      });
      renderWithProviders(<AssessmentHistory genomeId="g1" />);
      await waitFor(() => screen.getByText('低风险'));
    });
  });

  describe('数据格式兼容', () => {
    it('兼容顶层 assessments 数组', async () => {
      mockListAssessments.mockResolvedValue({
        assessments: [
          { id: 'a1', risk_level: 'HIGH', overall_risk_score: 0.7, core_loci_matched: 1, auxiliary_loci_matched: 1 },
        ],
      });
      renderWithProviders(<AssessmentHistory genomeId="g1" />);
      await waitFor(() => screen.getByText('高风险'));
    });
  });

  describe('选中回调', () => {
    it('点击评估卡片触发 onSelect', async () => {
      const assessment = {
        id: 'a1',
        risk_level: 'LOW',
        overall_risk_score: 0.12,
        core_loci_matched: 2,
        auxiliary_loci_matched: 5,
      };
      mockListAssessments.mockResolvedValue({
        data: { assessments: [assessment] },
      });
      const onSelect = vi.fn();
      renderWithProviders(
        <AssessmentHistory genomeId="g1" onSelect={onSelect} />
      );
      await waitFor(() => screen.getByText('低风险'));
      fireEvent.click(screen.getByText('低风险'));
      expect(onSelect).toHaveBeenCalledWith(
        expect.objectContaining({ id: 'a1' })
      );
    });
  });

  describe('抽屉模式', () => {
    it('open=true 时渲染遮罩与抽屉容器', async () => {
      mockListAssessments.mockResolvedValue({ data: { assessments: [] } });
      const { container } = renderWithProviders(
        <AssessmentHistory genomeId="g1" open={true} onClose={() => {}} />
      );
      await waitFor(() => screen.getByText('暂无历史评估'));
      // 遮罩层
      const overlay = container.querySelector('.fixed.inset-0');
      expect(overlay).not.toBeNull();
      // 关闭按钮（X 图标）
      const closeBtn = container.querySelector('button');
      expect(closeBtn).not.toBeNull();
    });

    it('open=false 时按常规模式渲染（无遮罩）', async () => {
      mockListAssessments.mockResolvedValue({ data: { assessments: [] } });
      const { container } = renderWithProviders(
        <AssessmentHistory genomeId="g1" open={false} onClose={() => {}} />
      );
      await waitFor(() => screen.getByText('暂无历史评估'));
      // 无遮罩层
      const overlay = container.querySelector('.fixed.inset-0');
      expect(overlay).toBeNull();
    });

    it('点击关闭按钮触发 onClose', async () => {
      mockListAssessments.mockResolvedValue({ data: { assessments: [] } });
      const onClose = vi.fn();
      const { container } = renderWithProviders(
        <AssessmentHistory genomeId="g1" open={true} onClose={onClose} />
      );
      await waitFor(() => screen.getByText('暂无历史评估'));
      const closeBtn = container.querySelector('button') as HTMLElement;
      fireEvent.click(closeBtn);
      expect(onClose).toHaveBeenCalled();
    });
  });
});
