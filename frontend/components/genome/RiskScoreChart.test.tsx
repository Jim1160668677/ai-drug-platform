import { describe, it, expect, vi } from 'vitest';
import { screen } from '@testing-library/react';
import RiskScoreChart from './RiskScoreChart';
import { renderWithProviders } from '@/lib/test-utils';

// mock PlotlyChart 避免在 jsdom 环境加载 plotly.js-dist-min
vi.mock('@/components/charts/PlotlyChart', () => ({
  default: ({ data }: { data: any[] }) => (
    <div data-testid="plotly-mock">
      {data?.[0]?.type ?? 'no-data'}
    </div>
  ),
}));

describe('RiskScoreChart 组件', () => {
  describe('加载与空态', () => {
    it('loading 状态显示骨架屏', () => {
      const { container } = renderWithProviders(
        <RiskScoreChart loading={true} />
      );
      const skeletons = container.querySelectorAll('.animate-pulse');
      expect(skeletons.length).toBeGreaterThan(0);
    });

    it('未提供 assessment 时显示空态提示', () => {
      renderWithProviders(<RiskScoreChart />);
      expect(
        screen.getByText('暂无风险评估结果，请先完成 AI 分析步骤')
      ).toBeInTheDocument();
    });
  });

  describe('风险等级展示', () => {
    it('LOW 等级显示低风险与绿色样式', () => {
      renderWithProviders(
        <RiskScoreChart
          assessment={{ risk_level: 'LOW', overall_risk_score: 0.12 }}
        />
      );
      expect(screen.getByText('低风险')).toBeInTheDocument();
      // 评分 12.0%
      expect(screen.getByText('12.0%')).toBeInTheDocument();
      expect(screen.getByText('遗传风险较低，建议保持健康生活方式')).toBeInTheDocument();
    });

    it('MODERATE 等级显示中等风险', () => {
      renderWithProviders(
        <RiskScoreChart
          assessment={{ risk_level: 'MODERATE', overall_risk_score: 0.45 }}
        />
      );
      expect(screen.getByText('中等风险')).toBeInTheDocument();
      expect(screen.getByText('45.0%')).toBeInTheDocument();
    });

    it('HIGH 等级显示高风险', () => {
      renderWithProviders(
        <RiskScoreChart
          assessment={{ risk_level: 'HIGH', overall_risk_score: 0.72 }}
        />
      );
      expect(screen.getByText('高风险')).toBeInTheDocument();
      expect(screen.getByText('72.0%')).toBeInTheDocument();
    });

    it('VERY_HIGH 等级显示极高风险', () => {
      renderWithProviders(
        <RiskScoreChart
          assessment={{ risk_level: 'VERY_HIGH', overall_risk_score: 0.91 }}
        />
      );
      expect(screen.getByText('极高风险')).toBeInTheDocument();
      expect(screen.getByText('91.0%')).toBeInTheDocument();
      expect(
        screen.getByText('遗传风险极高，建议咨询专业医生')
      ).toBeInTheDocument();
    });

    it('未知 risk_level 回退到 LOW 配置', () => {
      renderWithProviders(
        <RiskScoreChart
          assessment={{ risk_level: 'UNKNOWN', overall_risk_score: 0.05 }}
        />
      );
      expect(screen.getByText('低风险')).toBeInTheDocument();
    });

    it('overall_risk_score 缺省为 0 显示 0.0%', () => {
      renderWithProviders(
        <RiskScoreChart assessment={{ risk_level: 'LOW' }} />
      );
      expect(screen.getByText('0.0%')).toBeInTheDocument();
    });
  });

  describe('位点计数展示', () => {
    it('显示核心位点与辅助位点数量', () => {
      renderWithProviders(
        <RiskScoreChart
          assessment={{
            risk_level: 'HIGH',
            overall_risk_score: 0.6,
            core_loci_matched: 5,
            auxiliary_loci_matched: 12,
          }}
        />
      );
      expect(screen.getByText('5')).toBeInTheDocument();
      expect(screen.getByText('12')).toBeInTheDocument();
    });

    it('位点数量缺省为 0', () => {
      renderWithProviders(
        <RiskScoreChart
          assessment={{ risk_level: 'LOW', overall_risk_score: 0.1 }}
        />
      );
      // 核心位点 0 与辅助位点 0
      const zeros = screen.getAllByText('0');
      expect(zeros.length).toBeGreaterThanOrEqual(2);
    });
  });

  describe('雷达图渲染', () => {
    it('有风险位点时渲染雷达图', () => {
      renderWithProviders(
        <RiskScoreChart
          assessment={{ risk_level: 'HIGH', overall_risk_score: 0.6 }}
          matches={[
            { is_risk: true, risk_score: 0.8, locus: { rsid: 'rs1234' } },
            { is_risk: true, risk_score: 0.6, locus: { rsid: 'rs5678' } },
          ]}
        />
      );
      expect(screen.getByTestId('plotly-mock')).toBeInTheDocument();
      expect(screen.getByText('风险位点评分雷达图')).toBeInTheDocument();
    });

    it('仅含非风险位点时不渲染雷达图', () => {
      renderWithProviders(
        <RiskScoreChart
          assessment={{ risk_level: 'LOW', overall_risk_score: 0.1 }}
          matches={[
            { is_risk: false, risk_score: 0.2, locus: { rsid: 'rs1' } },
          ]}
        />
      );
      expect(screen.queryByTestId('plotly-mock')).not.toBeInTheDocument();
      expect(screen.queryByText('风险位点评分雷达图')).not.toBeInTheDocument();
    });

    it('matches 为空时不渲染雷达图', () => {
      renderWithProviders(
        <RiskScoreChart
          assessment={{ risk_level: 'LOW', overall_risk_score: 0.1 }}
          matches={[]}
        />
      );
      expect(screen.queryByTestId('plotly-mock')).not.toBeInTheDocument();
    });
  });
});
