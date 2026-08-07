/**
 * 干湿验证页面测试 — Kanban 看板 + 创建任务 + 记录结果 + 应用反馈
 *
 * 覆盖：
 * 1. 未选项目时显示提示
 * 2. 选中项目时渲染 5 列 Kanban + 任务卡片
 * 3. 新建验证任务 modal 提交
 * 4. 记录结果 modal 选择结论
 * 5. 应用反馈按钮触发 mutation
 */
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { screen, fireEvent, waitFor, cleanup } from '@testing-library/react';
import ValidationsPage from './page';
import { renderWithProviders } from '@/lib/test-utils';

// ===== mock store =====
const mockUseAppStore = vi.fn();
vi.mock('@/lib/store', () => ({
  useAppStore: (...args: any[]) => mockUseAppStore(...args),
}));

// ===== mock API =====
const mockListValidations = vi.fn();
const mockCreateValidation = vi.fn();
const mockRecordResult = vi.fn();
const mockApplyFeedback = vi.fn();

vi.mock('@/lib/api', async () => {
  const actual = await vi.importActual<typeof import('@/lib/api')>('@/lib/api');
  return {
    ...actual,
    listValidations: (...a: any[]) => mockListValidations(...a),
    createValidation: (...a: any[]) => mockCreateValidation(...a),
    recordResult: (...a: any[]) => mockRecordResult(...a),
    applyFeedback: (...a: any[]) => mockApplyFeedback(...a),
  };
});

// ===== mock notification =====
vi.mock('@/lib/notification', () => ({
  toast: { success: vi.fn(), error: vi.fn(), warning: vi.fn(), info: vi.fn() },
}));

// ===== fixture =====
const TASKS_FIXTURE = [
  {
    id: 'task-1',
    project_id: 'proj-1',
    target_id: 't-1',
    molecule_id: null,
    treatment_id: null,
    task_type: 'target_knockdown',
    hypothesis: 'EGFR 敲降抑制细胞活力',
    prediction: '细胞活力下降 30%',
    status: 'submitted',
    experiment_id: null,
    partner_id: null,
    submitted_at: '2026-07-22T00:00:00Z',
    result_received_at: null,
    actual_result: null,
    conclusion: null,
    feedback_applied: false,
    next_action: null,
    notes: null,
    created_at: '2026-07-22T00:00:00Z',
  },
  {
    id: 'task-2',
    project_id: 'proj-1',
    target_id: 't-2',
    molecule_id: null,
    treatment_id: null,
    task_type: 'cell_viability',
    hypothesis: '化合物 X 抑制 A549 增殖',
    prediction: 'IC50 < 1 μM',
    status: 'in_progress',
    experiment_id: null,
    partner_id: null,
    submitted_at: '2026-07-22T00:00:00Z',
    result_received_at: null,
    actual_result: null,
    conclusion: null,
    feedback_applied: false,
    next_action: null,
    notes: null,
    created_at: '2026-07-22T00:00:00Z',
  },
  {
    id: 'task-3',
    project_id: 'proj-1',
    target_id: 't-3',
    molecule_id: null,
    treatment_id: null,
    task_type: 'binding_assay',
    hypothesis: '化合物 Y 与靶点结合',
    prediction: 'Kd < 10 nM',
    status: 'validated',
    experiment_id: null,
    partner_id: null,
    submitted_at: '2026-07-22T00:00:00Z',
    result_received_at: '2026-07-22T00:00:00Z',
    actual_result: 'Kd = 5 nM',
    conclusion: 'validated',
    feedback_applied: false,
    next_action: '进入细胞实验',
    notes: null,
    created_at: '2026-07-22T00:00:00Z',
  },
];

describe('ValidationsPage', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mockListValidations.mockResolvedValue({ data: TASKS_FIXTURE });
    mockCreateValidation.mockResolvedValue(TASKS_FIXTURE[0]);
    mockRecordResult.mockResolvedValue({ ...TASKS_FIXTURE[2], status: 'validated' });
    mockApplyFeedback.mockResolvedValue({
      task_id: 'task-3',
      conclusion: 'validated',
      target_id: 't-3',
      target_confidence_before: 0.5,
      target_confidence_after: 0.6,
      molecule_id: null,
      molecule_status: null,
      feedback_applied: true,
    });
  });

  afterEach(() => cleanup());

  it('未选项目时显示提示', () => {
    mockUseAppStore.mockReturnValue({ currentProject: null });
    renderWithProviders(<ValidationsPage />);
    expect(screen.getByText(/请先在项目页选择一个项目/)).toBeInTheDocument();
  });

  it('选中项目时渲染 5 列 Kanban + 任务卡片', async () => {
    mockUseAppStore.mockReturnValue({ currentProject: { id: 'proj-1', name: '测试项目' } });
    renderWithProviders(<ValidationsPage />);

    // 5 列标题
    expect(screen.getByText('待验证')).toBeInTheDocument();
    expect(screen.getByText('进行中')).toBeInTheDocument();
    expect(screen.getByText('已验证')).toBeInTheDocument();
    expect(screen.getByText('已证伪')).toBeInTheDocument();
    expect(screen.getByText('不确定')).toBeInTheDocument();

    // 等待任务卡片渲染
    await waitFor(() => {
      expect(screen.getByText('EGFR 敲降抑制细胞活力')).toBeInTheDocument();
    });
    expect(screen.getByText('化合物 X 抑制 A549 增殖')).toBeInTheDocument();
    expect(screen.getByText('化合物 Y 与靶点结合')).toBeInTheDocument();
  });

  it('点击新建按钮打开创建 Modal 并可提交', async () => {
    mockUseAppStore.mockReturnValue({ currentProject: { id: 'proj-1', name: '测试项目' } });
    renderWithProviders(<ValidationsPage />);

    const createBtn = screen.getByText('新建验证任务');
    fireEvent.click(createBtn);

    // 用 placeholder 精确等待 Modal 输入框出现（按钮文字与 Modal 标题相同，会冲突）
    await waitFor(() => {
      expect(screen.getByPlaceholderText(/EGFR 敲降后 A549/)).toBeInTheDocument();
    });

    // 填写假设
    const hypothesisInput = screen.getByPlaceholderText(/EGFR 敲降后 A549/);
    fireEvent.change(hypothesisInput, { target: { value: '测试假设内容' } });

    // 提交
    const submitBtn = screen.getByText('提交');
    fireEvent.click(submitBtn);

    await waitFor(() => {
      expect(mockCreateValidation).toHaveBeenCalled();
    });
  });

  it('submitted 状态任务卡片显示"记录结果"按钮', async () => {
    mockUseAppStore.mockReturnValue({ currentProject: { id: 'proj-1', name: '测试项目' } });
    renderWithProviders(<ValidationsPage />);

    await waitFor(() => {
      expect(screen.getByText('EGFR 敲降抑制细胞活力')).toBeInTheDocument();
    });

    // submitted 状态可记录结果（按钮存在）
    const recordButtons = screen.getAllByText('记录结果');
    expect(recordButtons.length).toBeGreaterThan(0);
  });

  it('点击"记录结果"打开 Modal 并可选结论', async () => {
    mockUseAppStore.mockReturnValue({ currentProject: { id: 'proj-1', name: '测试项目' } });
    renderWithProviders(<ValidationsPage />);

    await waitFor(() => {
      expect(screen.getByText('EGFR 敲降抑制细胞活力')).toBeInTheDocument();
    });

    const recordButtons = screen.getAllByText('记录结果');
    fireEvent.click(recordButtons[0]);

    await waitFor(() => {
      expect(screen.getByText('记录实验结果')).toBeInTheDocument();
    });

    // 3 个结论按钮（task-3 卡片也显示"假设被验证"标签，故用 getAllByText）
    expect(screen.getAllByText('假设被验证').length).toBeGreaterThanOrEqual(1);
    expect(screen.getByText('假设被证伪')).toBeInTheDocument();
    expect(screen.getByText('结论不明确')).toBeInTheDocument();
  });

  it('validated 且未应用反馈的任务显示"应用反馈"按钮', async () => {
    mockUseAppStore.mockReturnValue({ currentProject: { id: 'proj-1', name: '测试项目' } });
    renderWithProviders(<ValidationsPage />);

    await waitFor(() => {
      expect(screen.getByText('化合物 Y 与靶点结合')).toBeInTheDocument();
    });

    // task-3 是 validated 且 feedback_applied=false → 应有"应用反馈"按钮
    const applyBtn = screen.getByText('应用反馈');
    fireEvent.click(applyBtn);

    await waitFor(() => {
      expect(mockApplyFeedback).toHaveBeenCalledWith('task-3');
    });
  });

  it('已应用反馈的任务显示"反馈已应用"标记', async () => {
    mockUseAppStore.mockReturnValue({ currentProject: { id: 'proj-1', name: '测试项目' } });
    // task-3 已应用反馈
    mockListValidations.mockResolvedValue({
      data: [{ ...TASKS_FIXTURE[2], feedback_applied: true }],
    });
    renderWithProviders(<ValidationsPage />);

    await waitFor(() => {
      expect(screen.getByText('反馈已应用')).toBeInTheDocument();
    });
  });

  it('应用反馈成功后显示置信度变化', async () => {
    mockUseAppStore.mockReturnValue({ currentProject: { id: 'proj-1', name: '测试项目' } });
    renderWithProviders(<ValidationsPage />);

    await waitFor(() => {
      expect(screen.getByText('化合物 Y 与靶点结合')).toBeInTheDocument();
    });

    const applyBtn = screen.getByText('应用反馈');
    fireEvent.click(applyBtn);

    await waitFor(() => {
      expect(screen.getByText(/靶点置信度 0.5 → 0.6/)).toBeInTheDocument();
    });
  });
});
