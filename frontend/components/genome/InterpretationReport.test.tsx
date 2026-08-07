import { describe, it, expect } from 'vitest';
import { screen } from '@testing-library/react';
import InterpretationReport from './InterpretationReport';
import { renderWithProviders } from '@/lib/test-utils';

describe('InterpretationReport 组件', () => {
  describe('加载与空态', () => {
    it('loading 状态显示骨架屏', () => {
      const { container } = renderWithProviders(
        <InterpretationReport interpretation={null} loading={true} />
      );
      const skeletons = container.querySelectorAll('.animate-pulse');
      expect(skeletons.length).toBeGreaterThan(0);
    });

    it('未提供 interpretation 显示空态提示', () => {
      renderWithProviders(<InterpretationReport interpretation={null} />);
      expect(
        screen.getByText('暂未生成解读报告，点击「生成 LLM 解读」按钮')
      ).toBeInTheDocument();
    });

    it('interpretation 为 undefined 显示空态', () => {
      renderWithProviders(
        <InterpretationReport interpretation={undefined as any} />
      );
      expect(
        screen.getByText('暂未生成解读报告，点击「生成 LLM 解读」按钮')
      ).toBeInTheDocument();
    });
  });

  describe('结构 ① 顶层字段', () => {
    it('渲染 summary / mechanism / action_items / disclaimer', () => {
      renderWithProviders(
        <InterpretationReport
          interpretation={{
            summary: '综合结论：风险略高',
            mechanism: '涉及 CYP2D6 代谢',
            action_items: ['建议 1', '建议 2'],
            disclaimer: '自定义免责声明',
            llm_model: 'agnes-2.0-flash',
          }}
        />
      );
      expect(screen.getByText('综合结论：风险略高')).toBeInTheDocument();
      expect(screen.getByText('涉及 CYP2D6 代谢')).toBeInTheDocument();
      expect(screen.getByText('建议 1')).toBeInTheDocument();
      expect(screen.getByText('建议 2')).toBeInTheDocument();
      expect(screen.getByText('自定义免责声明')).toBeInTheDocument();
      expect(screen.getByText('agnes-2.0-flash')).toBeInTheDocument();
    });

    it('disclaimer 缺省显示默认免责声明', () => {
      renderWithProviders(
        <InterpretationReport
          interpretation={{
            summary: '结论',
            llm_model: 'agnes',
          }}
        />
      );
      expect(
        screen.getByText('本报告仅供科研参考，不构成医疗建议')
      ).toBeInTheDocument();
    });
  });

  describe('结构 ② 嵌套 interpretation 子对象', () => {
    it('从 interpretation.interpretation 子对象读取字段', () => {
      renderWithProviders(
        <InterpretationReport
          interpretation={{
            llm_model: 'agnes',
            interpretation: {
              summary: '嵌套结论',
              mechanism: '嵌套机制',
              action_items: ['嵌套行动'],
              disclaimer: '嵌套免责',
            },
          }}
        />
      );
      expect(screen.getByText('嵌套结论')).toBeInTheDocument();
      expect(screen.getByText('嵌套机制')).toBeInTheDocument();
      expect(screen.getByText('嵌套行动')).toBeInTheDocument();
      expect(screen.getByText('嵌套免责')).toBeInTheDocument();
    });
  });

  describe('LLM 模型与降级标记', () => {
    it('显示 llm_model 徽章', () => {
      renderWithProviders(
        <InterpretationReport
          interpretation={{
            summary: '结论',
            llm_model: 'doubao-pro',
          }}
        />
      );
      expect(screen.getByText('doubao-pro')).toBeInTheDocument();
    });

    it('llm_model 为 rule_fallback 时显示"规则降级"徽章', () => {
      renderWithProviders(
        <InterpretationReport
          interpretation={{
            summary: '结论',
            llm_model: 'rule_fallback',
          }}
        />
      );
      expect(screen.getByText('规则降级')).toBeInTheDocument();
    });

    it('fallback=true 显示"规则降级"徽章', () => {
      renderWithProviders(
        <InterpretationReport
          interpretation={{
            summary: '结论',
            llm_model: 'agnes',
            fallback: true,
          }}
        />
      );
      expect(screen.getByText('规则降级')).toBeInTheDocument();
    });

    it('无 llm_model 时不渲染模型徽章', () => {
      renderWithProviders(
        <InterpretationReport
          interpretation={{ summary: '结论' }}
        />
      );
      // 标题仍在
      expect(screen.getByText('AI 解读报告')).toBeInTheDocument();
    });
  });

  describe('行动建议渲染', () => {
    it('action_items 为空数组时不渲染行动建议区块', () => {
      renderWithProviders(
        <InterpretationReport
          interpretation={{ summary: '结论', action_items: [] }}
        />
      );
      expect(screen.queryByText('行动建议')).not.toBeInTheDocument();
    });

    it('action_items 元素为对象时提取 content/text 字段', () => {
      renderWithProviders(
        <InterpretationReport
          interpretation={{
            summary: '结论',
            action_items: [
              { content: '对象形式建议' },
              { text: 'text 字段建议' },
            ],
          }}
        />
      );
      expect(screen.getByText('对象形式建议')).toBeInTheDocument();
      expect(screen.getByText('text 字段建议')).toBeInTheDocument();
    });

    it('action_items 元素为字符串时直接渲染', () => {
      renderWithProviders(
        <InterpretationReport
          interpretation={{
            summary: '结论',
            action_items: ['字符串建议'],
          }}
        />
      );
      expect(screen.getByText('字符串建议')).toBeInTheDocument();
    });
  });

  describe('summary / mechanism 缺省', () => {
    it('无 summary 时不渲染综合结论区块', () => {
      renderWithProviders(
        <InterpretationReport
          interpretation={{ mechanism: '机制', llm_model: 'agnes' }}
        />
      );
      expect(screen.queryByText('综合结论')).not.toBeInTheDocument();
    });

    it('无 mechanism 时不渲染机制解读区块', () => {
      renderWithProviders(
        <InterpretationReport
          interpretation={{ summary: '结论', llm_model: 'agnes' }}
        />
      );
      expect(screen.queryByText('机制解读')).not.toBeInTheDocument();
    });
  });
});
