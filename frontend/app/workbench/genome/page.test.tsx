import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { screen, fireEvent, waitFor, act, cleanup } from '@testing-library/react';
import GenomePage from './page';
import { renderWithProviders } from '@/lib/test-utils';

vi.mock('next/navigation', () => ({
  useRouter: () => ({ push: vi.fn(), replace: vi.fn(), refresh: vi.fn(), back: vi.fn() }),
}));

// ===== mock store =====
const mockSetSelectedGenome = vi.fn();
const mockUseAppStore = vi.fn();
vi.mock('@/lib/store', () => ({
  useAppStore: (...args: any[]) => mockUseAppStore(...args),
}));

// ===== mock API =====
const mockMatchGenotype = vi.fn();
const mockScoreRisk = vi.fn();
const mockInterpret = vi.fn();
const mockGenerateRecommendations = vi.fn();
const mockPersonalizedTreatment = vi.fn();
const mockListRecommendations = vi.fn();
const mockListAssessments = vi.fn();

vi.mock('@/lib/api', () => ({
  matchGenotype: (...a: any[]) => mockMatchGenotype(...a),
  scoreRisk: (...a: any[]) => mockScoreRisk(...a),
  interpret: (...a: any[]) => mockInterpret(...a),
  generateRecommendations: (...a: any[]) => mockGenerateRecommendations(...a),
  personalizedTreatment: (...a: any[]) => mockPersonalizedTreatment(...a),
  listRecommendations: (...a: any[]) => mockListRecommendations(...a),
  listAssessments: (...a: any[]) => mockListAssessments(...a),
}));

vi.mock('@/lib/notification', () => ({
  toast: { success: vi.fn(), error: vi.fn(), warning: vi.fn(), info: vi.fn() },
}));

// ===== mock 子组件：暴露交互钩子 =====
// 这些回调在测试中通过 act() 包裹调用，确保 React 状态同步刷新。
let uploaderOnUploaded: ((g: any) => void) | null = null;
vi.mock('@/components/genome/GenomeUploader', () => ({
  default: ({ onUploaded }: { onUploaded?: (g: any) => void }) => {
    uploaderOnUploaded = onUploaded;
    return <div data-testid="genome-uploader">GenomeUploader</div>;
  },
}));

let fileListOnSelect: ((g: any) => void) | null = null;
vi.mock('@/components/genome/GenomeFileList', () => ({
  default: ({ onSelect }: { onSelect?: (g: any) => void }) => {
    fileListOnSelect = onSelect;
    return <div data-testid="genome-file-list">GenomeFileList</div>;
  },
}));

let traitOnChange: ((ids: string[]) => void) | null = null;
vi.mock('@/components/genome/TraitSelector', () => ({
  default: ({ onChange }: { onChange?: (ids: string[]) => void }) => {
    traitOnChange = onChange;
    return <div data-testid="trait-selector">TraitSelector</div>;
  },
}));

vi.mock('@/components/genome/LociSearchPanel', () => ({
  default: () => <div data-testid="loci-search-panel">LociSearchPanel</div>,
}));

vi.mock('@/components/genome/AssessmentHistory', () => ({
  default: ({ open, onClose, onSelect }: any) => (
    <div data-testid="assessment-history" data-open={open ? 'true' : 'false'}>
      AssessmentHistory
      {open && (
        <button data-testid="history-close" onClick={onClose}>close</button>
      )}
      <button
        data-testid="history-select"
        onClick={() => onSelect?.({ id: 'a1', risk_level: 'HIGH', overall_risk_score: 0.7 })}
      >
        select
      </button>
    </div>
  ),
}));

vi.mock('@/components/genome/RiskScoreChart', () => ({
  default: ({ assessment }: any) => (
    <div data-testid="risk-score-chart" data-has-assessment={assessment ? 'true' : 'false'}>
      RiskScoreChart
    </div>
  ),
}));

vi.mock('@/components/genome/InterpretationReport', () => ({
  default: ({ interpretation }: any) => (
    <div data-testid="interpretation-report">
      {interpretation ? interpretation.summary : 'empty'}
    </div>
  ),
}));

vi.mock('@/components/genome/RecommendationList', () => ({
  default: ({ recommendations }: any) => (
    <div data-testid="recommendation-list">{recommendations?.length || 0} items</div>
  ),
}));

vi.mock('@/components/genome/PersonalizedTreatmentCard', () => ({
  default: ({ data }: any) => (
    <div data-testid="treatment-card">{data ? data.disease : 'empty'}</div>
  ),
}));

const GENOME = { id: 'g1', file_name: 'genome.txt', total_variants: 100 };

// 用 act() 包裹直接调用子组件回调，确保 React 状态同步刷新后再断言/交互
const uploadGenome = (g: any = GENOME) =>
  act(() => { uploaderOnUploaded!(g); });
const selectFile = (g: any = GENOME) =>
  act(() => { fileListOnSelect!(g); });
const selectTraits = (ids: string[]) =>
  act(() => { traitOnChange!(ids); });

describe('GenomePage 个人基因组解读页面', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    uploaderOnUploaded = null;
    fileListOnSelect = null;
    traitOnChange = null;
    mockUseAppStore.mockReturnValue({
      currentProject: { id: 'p1', name: '测试项目' },
      setSelectedGenome: mockSetSelectedGenome,
    });
  });

  // 显式清理 testing-library DOM，避免测试间 DOM 累积导致
  // getByText 找到多个相同文本（如多个"查看报告"按钮残留）。
  afterEach(() => {
    cleanup();
  });

  describe('初始渲染', () => {
    it('显示页面标题与说明', () => {
      renderWithProviders(<GenomePage />);
      expect(screen.getByText('个人基因组解读')).toBeInTheDocument();
      expect(screen.getByText(/上传 SNP 芯片数据/)).toBeInTheDocument();
    });

    it('显示 4 步 Stepper', () => {
      renderWithProviders(<GenomePage />);
      expect(screen.getByText('上传文件')).toBeInTheDocument();
      expect(screen.getByText('选择性状')).toBeInTheDocument();
      expect(screen.getByText('AI 分析')).toBeInTheDocument();
      expect(screen.getByText('查看报告')).toBeInTheDocument();
    });

    it('初始处于 Step 1，渲染上传组件', () => {
      renderWithProviders(<GenomePage />);
      expect(screen.getByTestId('genome-uploader')).toBeInTheDocument();
      expect(screen.getByTestId('genome-file-list')).toBeInTheDocument();
    });

    it('未选择基因组时"下一步"按钮禁用', () => {
      renderWithProviders(<GenomePage />);
      const nextBtn = screen.getByText('下一步：选择性状').closest('button');
      expect(nextBtn).toBeDisabled();
    });

    it('未选择基因组时"历史评估"按钮禁用', () => {
      renderWithProviders(<GenomePage />);
      const historyBtn = screen.getByText('历史评估').closest('button');
      expect(historyBtn).toBeDisabled();
    });
  });

  describe('Step 1 → Step 2 流转', () => {
    it('上传成功后选择基因组，启用"下一步"', () => {
      renderWithProviders(<GenomePage />);
      uploadGenome();
      const nextBtn = screen.getByText('下一步：选择性状').closest('button');
      expect(nextBtn).not.toBeDisabled();
    });

    it('通过 GenomeFileList 选中基因组', () => {
      renderWithProviders(<GenomePage />);
      selectFile();
      const nextBtn = screen.getByText('下一步：选择性状').closest('button');
      expect(nextBtn).not.toBeDisabled();
    });

    it('选中基因组后调用 store.setSelectedGenome', () => {
      renderWithProviders(<GenomePage />);
      uploadGenome();
      expect(mockSetSelectedGenome).toHaveBeenCalledWith('g1');
    });

    it('点击"下一步"进入 Step 2', () => {
      renderWithProviders(<GenomePage />);
      uploadGenome();
      fireEvent.click(screen.getByText('下一步：选择性状'));
      expect(screen.getByText('Step 2 · 选择感兴趣的性状')).toBeInTheDocument();
      expect(screen.getByTestId('trait-selector')).toBeInTheDocument();
      expect(screen.getByText(/genome\.txt/)).toBeInTheDocument();
    });
  });

  describe('Step 2 性状选择', () => {
    it('未选择性状时"下一步"禁用', () => {
      renderWithProviders(<GenomePage />);
      uploadGenome();
      fireEvent.click(screen.getByText('下一步：选择性状'));
      const nextBtn = screen.getByText('下一步：AI 分析').closest('button');
      expect(nextBtn).toBeDisabled();
    });

    it('选择性状后"下一步"启用', () => {
      renderWithProviders(<GenomePage />);
      uploadGenome();
      fireEvent.click(screen.getByText('下一步：选择性状'));
      selectTraits(['t1']);
      const nextBtn = screen.getByText('下一步：AI 分析').closest('button');
      expect(nextBtn).not.toBeDisabled();
    });

    it('点击"下一步"进入 Step 3', () => {
      renderWithProviders(<GenomePage />);
      uploadGenome();
      fireEvent.click(screen.getByText('下一步：选择性状'));
      selectTraits(['t1']);
      fireEvent.click(screen.getByText('下一步：AI 分析'));
      expect(screen.getByText('Step 3 · AI 检索位点 + 基因型匹配 + 风险评估')).toBeInTheDocument();
      expect(screen.getByTestId('loci-search-panel')).toBeInTheDocument();
    });

    it('点击"上一步"返回 Step 1', () => {
      renderWithProviders(<GenomePage />);
      uploadGenome();
      fireEvent.click(screen.getByText('下一步：选择性状'));
      fireEvent.click(screen.getByText('上一步'));
      expect(screen.getByText('Step 1 · 上传 SNP 芯片文件')).toBeInTheDocument();
    });
  });

  describe('Step 3 AI 分析', () => {
    const enterStep3 = () => {
      renderWithProviders(<GenomePage />);
      uploadGenome();
      fireEvent.click(screen.getByText('下一步：选择性状'));
      selectTraits(['t1']);
      fireEvent.click(screen.getByText('下一步：AI 分析'));
    };

    it('基因型匹配按钮初始可用', () => {
      enterStep3();
      const matchBtn = screen.getByText('1. 基因型匹配').closest('button');
      expect(matchBtn).not.toBeDisabled();
    });

    it('风险评估按钮在无匹配结果时禁用', () => {
      enterStep3();
      const scoreBtn = screen.getByText('2. 风险评估').closest('button');
      expect(scoreBtn).toBeDisabled();
    });

    it('点击基因型匹配调用 matchGenotype', async () => {
      mockMatchGenotype.mockResolvedValue({
        data: { matches: [{ id: 'm1', is_risk: true, user_genotype: 'AA', risk_score: 0.8 }] },
      });
      enterStep3();
      await act(async () => {
        fireEvent.click(screen.getByText('1. 基因型匹配'));
      });
      await waitFor(() => {
        expect(mockMatchGenotype).toHaveBeenCalledWith('g1', 't1');
      });
    });

    it('匹配成功后显示匹配结果摘要并启用风险评估', async () => {
      mockMatchGenotype.mockResolvedValue({
        data: {
          matches: [
            { id: 'm1', is_risk: true, user_genotype: 'AA', risk_score: 0.8 },
            { id: 'm2', is_risk: false, user_genotype: 'GG', risk_score: 0.1 },
          ],
        },
      });
      enterStep3();
      await act(async () => {
        fireEvent.click(screen.getByText('1. 基因型匹配'));
      });
      await waitFor(() => {
        expect(screen.getByText(/匹配结果：2 个位点/)).toBeInTheDocument();
        expect(screen.getByText('AA')).toBeInTheDocument();
      });
      const scoreBtn = screen.getByText('2. 风险评估').closest('button');
      expect(scoreBtn).not.toBeDisabled();
    });

    it('风险评估成功后启用"查看报告"', async () => {
      mockMatchGenotype.mockResolvedValue({
        data: { matches: [{ id: 'm1', is_risk: true, user_genotype: 'AA', risk_score: 0.8 }] },
      });
      mockScoreRisk.mockResolvedValue({
        data: { id: 'a1', risk_level: 'HIGH', overall_risk_score: 0.7, core_loci_matched: 1, auxiliary_loci_matched: 0 },
      });
      enterStep3();
      await act(async () => {
        fireEvent.click(screen.getByText('1. 基因型匹配'));
      });
      await waitFor(() => screen.getByText('AA'));
      await act(async () => {
        fireEvent.click(screen.getByText('2. 风险评估'));
      });
      await waitFor(() => expect(mockScoreRisk).toHaveBeenCalledWith('g1', 't1'));
      // 注意：Stepper 步骤 4 标签也是"查看报告"文本，须用 role=button 精确定位按钮
      const reportBtn = screen.getByRole('button', { name: '查看报告' });
      expect(reportBtn).not.toBeDisabled();
    });
  });

  describe('Step 4 报告页', () => {
    const goToStep4 = async () => {
      mockMatchGenotype.mockResolvedValue({
        data: { matches: [{ id: 'm1', is_risk: true, user_genotype: 'AA', risk_score: 0.8 }] },
      });
      mockScoreRisk.mockResolvedValue({
        data: { id: 'a1', risk_level: 'HIGH', overall_risk_score: 0.7, core_loci_matched: 1, auxiliary_loci_matched: 0 },
      });
      renderWithProviders(<GenomePage />);
      uploadGenome();
      fireEvent.click(screen.getByText('下一步：选择性状'));
      selectTraits(['t1']);
      fireEvent.click(screen.getByText('下一步：AI 分析'));
      await act(async () => {
        fireEvent.click(screen.getByText('1. 基因型匹配'));
      });
      await waitFor(() => screen.getByText('AA'));
      await act(async () => {
        fireEvent.click(screen.getByText('2. 风险评估'));
      });
      // Stepper 步骤 4 标签也是"查看报告"文本，须用 role=button 精确定位按钮
      await waitFor(() => screen.getByRole('button', { name: '查看报告' }));
      fireEvent.click(screen.getByRole('button', { name: '查看报告' }));
    };

    it('渲染风险评分图、解读报告、生活建议、治疗卡片', async () => {
      await goToStep4();
      expect(screen.getByTestId('risk-score-chart')).toBeInTheDocument();
      expect(screen.getByTestId('interpretation-report')).toBeInTheDocument();
      expect(screen.getByTestId('recommendation-list')).toBeInTheDocument();
      expect(screen.getByTestId('treatment-card')).toBeInTheDocument();
    });

    it('点击"生成 LLM 解读"调用 interpret', async () => {
      mockInterpret.mockResolvedValue({ data: { id: 'a1', summary: '解读结论', llm_model: 'agnes' } });
      await goToStep4();
      fireEvent.click(screen.getByText('生成 LLM 解读'));
      await waitFor(() => expect(mockInterpret).toHaveBeenCalledWith('a1', { use_llm: true }));
    });

    it('点击"生成生活建议"调用 generateRecommendations', async () => {
      mockGenerateRecommendations.mockResolvedValue({
        data: { recommendations: [{ id: 'r1', content: '建议 A' }] },
      });
      await goToStep4();
      fireEvent.click(screen.getByText('生成生活建议'));
      await waitFor(() => expect(mockGenerateRecommendations).toHaveBeenCalledWith('a1'));
    });

    it('点击"生成治疗推荐"调用 personalizedTreatment', async () => {
      mockPersonalizedTreatment.mockResolvedValue({ data: { disease: '高血压', llm_model: 'agnes' } });
      await goToStep4();
      fireEvent.click(screen.getByText('生成治疗推荐'));
      await waitFor(() => {
        expect(mockPersonalizedTreatment).toHaveBeenCalledWith(
          expect.objectContaining({ personal_genome_id: 'g1', project_id: 'p1' })
        );
      });
    });

    it('点击"开始新一次分析"重置状态回到 Step 1', async () => {
      await goToStep4();
      fireEvent.click(screen.getByText('开始新一次分析'));
      expect(screen.getByText('Step 1 · 上传 SNP 芯片文件')).toBeInTheDocument();
      const nextBtn = screen.getByText('下一步：选择性状').closest('button');
      expect(nextBtn).toBeDisabled();
    });
  });

  describe('历史评估抽屉', () => {
    it('选择基因组后启用"历史评估"按钮', () => {
      renderWithProviders(<GenomePage />);
      uploadGenome();
      const historyBtn = screen.getByText('历史评估').closest('button');
      expect(historyBtn).not.toBeDisabled();
    });

    it('点击"历史评估"打开抽屉', () => {
      renderWithProviders(<GenomePage />);
      uploadGenome();
      fireEvent.click(screen.getByText('历史评估'));
      const history = screen.getByTestId('assessment-history');
      expect(history.getAttribute('data-open')).toBe('true');
    });

    it('选中历史评估后跳到 Step 4', () => {
      renderWithProviders(<GenomePage />);
      uploadGenome();
      fireEvent.click(screen.getByText('历史评估'));
      fireEvent.click(screen.getByTestId('history-select'));
      expect(screen.getByText('Step 4 · 风险评估报告')).toBeInTheDocument();
    });

    it('点击关闭按钮关闭抽屉', async () => {
      renderWithProviders(<GenomePage />);
      uploadGenome();
      fireEvent.click(screen.getByText('历史评估'));
      const closeBtn = await screen.findByTestId('history-close');
      fireEvent.click(closeBtn);
      const history = screen.getByTestId('assessment-history');
      expect(history.getAttribute('data-open')).toBe('false');
    });
  });

  describe('无项目上下文', () => {
    it('currentProject 为空时页面仍可渲染', () => {
      mockUseAppStore.mockReturnValue({
        currentProject: null,
        setSelectedGenome: mockSetSelectedGenome,
      });
      renderWithProviders(<GenomePage />);
      expect(screen.getByText('个人基因组解读')).toBeInTheDocument();
    });
  });
});
