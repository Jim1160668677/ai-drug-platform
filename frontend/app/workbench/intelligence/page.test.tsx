import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, fireEvent } from '@testing-library/react';
import { renderWithProviders } from '@/lib/test-utils';

vi.mock('next/navigation', () => ({
  useSearchParams: () => new URLSearchParams(''),
  useRouter: () => ({ push: vi.fn(), replace: vi.fn(), refresh: vi.fn() }),
}));

vi.mock('@/hooks/useMediaQuery', () => ({
  useResponsiveLayout: () => ({ isDesktop: true, isTablet: false, isMobile: false }),
  useMediaQuery: () => false,
}));

vi.mock('@/hooks/useIntelligenceChat', () => ({
  useIntelligenceChat: () => ({
    messages: [], send: vi.fn(), clearMessages: vi.fn(), isSending: false,
    useStream: false, setUseStream: vi.fn(), streamStatus: 'idle', abortStream: vi.fn(),
  }),
}));

vi.mock('@/lib/api', () => ({
  listSessions: vi.fn().mockResolvedValue({ items: [], total: 0 }),
  createSession: vi.fn(), archiveSession: vi.fn(), getSession: vi.fn(),
  forceMode: vi.fn(), sendChat: vi.fn(),
  getContext: vi.fn().mockResolvedValue({ session_id: '', memories: [], context_prompt: '' }),
  getTrace: vi.fn().mockResolvedValue({ session_id: '', total_steps: 0, traces: [] }),
  getTraceTree: vi.fn(), getCostBreakdown: vi.fn(), getDecisionChain: vi.fn(),
  collectEvidence: vi.fn(), collectEntityContext: vi.fn(),
  interpretAnalysis: vi.fn(), interpretDataset: vi.fn(),
  normalizeMultimodal: vi.fn(), analyzeVision: vi.fn(),
  listRules: vi.fn().mockResolvedValue({ presets: [], rulesets: [], total_rules: 0 }),
  getRulePreset: vi.fn(), executeRules: vi.fn(), validateRules: vi.fn(),
}));

vi.mock('@/lib/store', () => ({
  useAppStore: (selector?: (s: { currentProject: null }) => unknown) => {
    const state = { currentProject: null };
    return selector ? selector(state) : state;
  },
}));

vi.mock('@/lib/notification', () => ({
  toast: { success: vi.fn(), error: vi.fn(), warning: vi.fn(), info: vi.fn() },
}));

import IntelligencePage from './page';

describe('IntelligencePage 集成测试', () => {
  beforeEach(() => { vi.clearAllMocks(); });

  it('页面渲染不崩溃', () => {
    renderWithProviders(<IntelligencePage />);
    expect(document.body).toBeInTheDocument();
  });

  it('未选会话显示空状态提示', () => {
    renderWithProviders(<IntelligencePage />);
    expect(screen.getByText('请选择或新建会话')).toBeInTheDocument();
  });

  it('右栏标签页切换', () => {
    renderWithProviders(<IntelligencePage />);
    expect(screen.getByText('上下文')).toBeInTheDocument();
    expect(screen.getByText('追溯')).toBeInTheDocument();
    expect(screen.getByText('证据')).toBeInTheDocument();
    expect(screen.getByText('流程DAG')).toBeInTheDocument();
    expect(screen.getByText('分析')).toBeInTheDocument();
  });

  it('切换到证据标签显示空状态', () => {
    renderWithProviders(<IntelligencePage />);
    fireEvent.click(screen.getByText('证据'));
    expect(screen.getByText('选择会话后查看')).toBeInTheDocument();
  });

  it('切换到分析标签不崩溃', () => {
    renderWithProviders(<IntelligencePage />);
    fireEvent.click(screen.getByText('分析'));
    expect(document.body).toBeInTheDocument();
  });
});