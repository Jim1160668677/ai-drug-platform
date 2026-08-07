import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, fireEvent, waitFor } from '@testing-library/react';
import { renderWithProviders } from '@/lib/test-utils';

// mock next/dynamic：直接返回组件工厂
vi.mock('next/dynamic', () => ({
  default: () => {
    const MockEditor = (props: { value?: string; onChange?: (v: string) => void }) => (
      <textarea
        data-testid="mock-monaco"
        value={props.value || ''}
        onChange={(e) => props.onChange?.(e.target.value)}
      />
    );
    return MockEditor;
  },
}));

vi.mock('@/lib/api', () => ({
  validateRules: vi.fn(),
  executeRules: vi.fn(),
}));

import { validateRules, executeRules } from '@/lib/api';
const mockedValidateRules = vi.mocked(validateRules);
const mockedExecuteRules = vi.mocked(executeRules);

import RulePlayground from './RulePlayground';

beforeEach(() => {
  vi.clearAllMocks();
});

describe('RulePlayground', () => {
  it('渲染标题和编辑器', () => {
    renderWithProviders(<RulePlayground />);
    expect(screen.getByText('规则演练场')).toBeInTheDocument();
  });

  it('点击校验按钮调用 validateRules', async () => {
    mockedValidateRules.mockResolvedValue({ valid: true, errors: [], rules_count: 1 });
    renderWithProviders(<RulePlayground />);
    fireEvent.click(screen.getByText('校验规则'));
    await waitFor(() => expect(mockedValidateRules).toHaveBeenCalled());
  });

  it('点击执行按钮调用 executeRules', async () => {
    mockedExecuteRules.mockResolvedValue({
      ruleset_name: 'test', total_rules: 1, matched_rules: 1,
      executed_actions: 1, results: [], context_changes: {}, duration_sec: 0.1,
    });
    renderWithProviders(<RulePlayground />);
    fireEvent.click(screen.getByText('执行规则'));
    await waitFor(() => expect(mockedExecuteRules).toHaveBeenCalled());
  });
});