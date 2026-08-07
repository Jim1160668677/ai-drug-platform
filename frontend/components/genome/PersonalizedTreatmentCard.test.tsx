import { describe, it, expect } from 'vitest';
import { screen } from '@testing-library/react';
import PersonalizedTreatmentCard from './PersonalizedTreatmentCard';
import { renderWithProviders } from '@/lib/test-utils';

describe('PersonalizedTreatmentCard 组件', () => {
  describe('加载与空态', () => {
    it('loading 状态显示骨架屏', () => {
      const { container } = renderWithProviders(
        <PersonalizedTreatmentCard loading={true} />
      );
      const skeletons = container.querySelectorAll('.animate-pulse');
      expect(skeletons.length).toBeGreaterThan(0);
    });

    it('未提供 data 显示空态提示', () => {
      renderWithProviders(<PersonalizedTreatmentCard data={null} />);
      expect(
        screen.getByText('暂无个性化治疗推荐，点击「生成治疗推荐」按钮')
      ).toBeInTheDocument();
    });

    it('data 为 undefined 显示空态', () => {
      renderWithProviders(
        <PersonalizedTreatmentCard data={undefined as any} />
      );
      expect(
        screen.getByText('暂无个性化治疗推荐，点击「生成治疗推荐」按钮')
      ).toBeInTheDocument();
    });
  });

  describe('头部信息', () => {
    it('显示 disease 徽章', () => {
      renderWithProviders(
        <PersonalizedTreatmentCard
          data={{
            disease: '2型糖尿病',
            llm_model: 'agnes-2.0-flash',
          }}
        />
      );
      expect(screen.getByText('疾病：2型糖尿病')).toBeInTheDocument();
    });

    it('显示 llm_model 徽章', () => {
      renderWithProviders(
        <PersonalizedTreatmentCard
          data={{ disease: '高血压', llm_model: 'doubao-pro' }}
        />
      );
      expect(screen.getByText('doubao-pro')).toBeInTheDocument();
    });

    it('无 disease 不渲染疾病徽章', () => {
      renderWithProviders(
        <PersonalizedTreatmentCard data={{ llm_model: 'agnes' }}
        />
      );
      expect(screen.queryByText(/疾病：/)).not.toBeInTheDocument();
    });

    it('无 llm_model 不渲染模型徽章', () => {
      renderWithProviders(
        <PersonalizedTreatmentCard data={{ disease: 'X' }} />
      );
      expect(screen.queryByText('agnes-2.0-flash')).not.toBeInTheDocument();
    });
  });

  describe('药物候选列表', () => {
    it('渲染药物候选并显示数量', () => {
      renderWithProviders(
        <PersonalizedTreatmentCard
          data={{
            drug_candidates: [
              { id: 'd1', name: '二甲双胍', indication: '糖尿病', mechanism: 'AMPK' },
              { id: 'd2', drug_name: '格列美脲', indication: '糖尿病' },
            ],
          }}
        />
      );
      expect(screen.getByText('候选药物（2）')).toBeInTheDocument();
      expect(screen.getByText('二甲双胍')).toBeInTheDocument();
      expect(screen.getByText('格列美脲')).toBeInTheDocument();
      // 两个药物 indication 均为"糖尿病"，应匹配多个
      expect(screen.getAllByText('糖尿病').length).toBe(2);
    });

    it('药物无 name 时显示 —', () => {
      renderWithProviders(
        <PersonalizedTreatmentCard
          data={{
            drug_candidates: [{ id: 'd1', indication: 'X' }],
          }}
        />
      );
      expect(screen.getByText('—')).toBeInTheDocument();
    });
  });

  describe('LLM 个性化用药建议', () => {
    it('渲染字符串形式建议', () => {
      renderWithProviders(
        <PersonalizedTreatmentCard
          data={{
            recommendations: ['建议服用低剂量', '监测肝功能'],
          }}
        />
      );
      expect(screen.getByText('建议服用低剂量')).toBeInTheDocument();
      expect(screen.getByText('监测肝功能')).toBeInTheDocument();
    });

    it('渲染对象形式建议（content / text）', () => {
      renderWithProviders(
        <PersonalizedTreatmentCard
          data={{
            recommendations: [
              { content: '对象形式建议' },
              { text: 'text 形式建议' },
            ],
          }}
        />
      );
      expect(screen.getByText('对象形式建议')).toBeInTheDocument();
      expect(screen.getByText('text 形式建议')).toBeInTheDocument();
    });
  });

  describe('基因-药物相互作用警示', () => {
    it('渲染字符串形式警示', () => {
      renderWithProviders(
        <PersonalizedTreatmentCard
          data={{
            gene_drug_interactions: ['CYP2D6 慢代谢者慎用'],
          }}
        />
      );
      expect(screen.getByText('CYP2D6 慢代谢者慎用')).toBeInTheDocument();
      expect(screen.getByText('基因-药物相互作用警示')).toBeInTheDocument();
    });

    it('渲染对象形式警示（description / warning）', () => {
      renderWithProviders(
        <PersonalizedTreatmentCard
          data={{
            gene_drug_interactions: [
              { description: 'SLCO1B1 风险' },
              { warning: '华法林敏感' },
            ],
          }}
        />
      );
      expect(screen.getByText('SLCO1B1 风险')).toBeInTheDocument();
      expect(screen.getByText('华法林敏感')).toBeInTheDocument();
    });
  });

  describe('剂量调整建议', () => {
    it('渲染字符串形式剂量建议', () => {
      renderWithProviders(
        <PersonalizedTreatmentCard
          data={{
            dosage_adjustments: ['起始剂量减半'],
          }}
        />
      );
      expect(screen.getByText('起始剂量减半')).toBeInTheDocument();
      expect(screen.getByText('剂量调整建议')).toBeInTheDocument();
    });

    it('渲染对象形式剂量建议（description / recommendation）', () => {
      renderWithProviders(
        <PersonalizedTreatmentCard
          data={{
            dosage_adjustments: [
              { description: '剂量 25mg' },
              { recommendation: '每周监测' },
            ],
          }}
        />
      );
      expect(screen.getByText('剂量 25mg')).toBeInTheDocument();
      expect(screen.getByText('每周监测')).toBeInTheDocument();
    });
  });

  describe('空数据兜底', () => {
    it('所有列表为空时显示"暂无可用推荐数据"', () => {
      renderWithProviders(
        <PersonalizedTreatmentCard
          data={{
            disease: 'X',
            llm_model: 'agnes',
            recommendations: [],
            drug_candidates: [],
            gene_drug_interactions: [],
            dosage_adjustments: [],
          }}
        />
      );
      expect(screen.getByText('暂无可用推荐数据')).toBeInTheDocument();
    });

    it('始终显示"本推荐仅供参考"免责声明', () => {
      renderWithProviders(
        <PersonalizedTreatmentCard data={{ disease: 'X' }} />
      );
      expect(
        screen.getByText('本推荐仅供参考，具体用药请遵医嘱')
      ).toBeInTheDocument();
    });
  });
});
