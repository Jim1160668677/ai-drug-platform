import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, fireEvent, waitFor } from '@testing-library/react';
import { renderWithProviders } from '@/lib/test-utils';

vi.mock('@/lib/api', () => ({ forceMode: vi.fn() }));
vi.mock('@/lib/notification', () => ({ toast: { success: vi.fn(), error: vi.fn(), warning: vi.fn(), info: vi.fn() } }));

import { forceMode } from '@/lib/api';
const mockedForceMode = vi.mocked(forceMode);
import ModeSwitcher from './ModeSwitcher';

beforeEach(() => { vi.clearAllMocks(); });

describe('ModeSwitcher', () => {
  it('渲染五个模式按钮', () => {
    renderWithProviders(<ModeSwitcher sessionId="s1" currentMode="chat" />);
    expect(screen.getByText('问答')).toBeInTheDocument();
    expect(screen.getByText('推理')).toBeInTheDocument();
    expect(screen.getByText('Agent')).toBeInTheDocument();
    expect(screen.getByText('混合')).toBeInTheDocument();
    expect(screen.getByText('自动')).toBeInTheDocument();
  });

  it('点击模式触发 forceMode', async () => {
    mockedForceMode.mockResolvedValue({ primary_mode: 'reasoning' });
    renderWithProviders(<ModeSwitcher sessionId="s1" currentMode="chat" />);
    fireEvent.click(screen.getByText('推理'));
    await waitFor(() => expect(mockedForceMode).toHaveBeenCalledWith('s1', 'reasoning'));
  });

  it('显示 intent 路由信息', () => {
    renderWithProviders(
      <ModeSwitcher sessionId="s1" currentMode="auto"
        intent={{ mode: 'reasoning', confidence: 0.85, reason: 'test', method: 'auto' }} />,
    );
    expect(screen.getByText('reasoning')).toBeInTheDocument();
    expect(screen.getByText('(85%)')).toBeInTheDocument();
  });
});