import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen } from '@testing-library/react';
import { renderWithProviders } from '@/lib/test-utils';

vi.mock('@/lib/api', () => ({
  listRules: vi.fn(),
  getRulePreset: vi.fn(),
}));

import { listRules, getRulePreset } from '@/lib/api';
const mockedListRules = vi.mocked(listRules);
const mockedGetRulePreset = vi.mocked(getRulePreset);

import RuleExplorer from './RuleExplorer';

beforeEach(() => {
  vi.clearAllMocks();
  mockedListRules.mockResolvedValue({
    presets: ['safety', 'toxicity'],
    rulesets: [],
    total_rules: 5,
  });
  mockedGetRulePreset.mockResolvedValue({
    name: 'safety',
    version: '1.0',
    description: '安全规则',
    rules: [
      { id: 'r1', name: '安全检查', when: {}, then: [], priority: 1, enabled: true },
    ],
  });
});

describe('RuleExplorer', () => {
  it('渲染标题', () => {
    renderWithProviders(<RuleExplorer />);
    expect(screen.getByText('规则浏览器')).toBeInTheDocument();
  });

  it('渲染 preset 列表', async () => {
    renderWithProviders(<RuleExplorer />);
    expect(await screen.findByText('safety')).toBeInTheDocument();
    expect(screen.getByText('toxicity')).toBeInTheDocument();
  });

  it('渲染规则详情', async () => {
    renderWithProviders(<RuleExplorer />);
    expect(await screen.findByText('安全检查')).toBeInTheDocument();
  });
});