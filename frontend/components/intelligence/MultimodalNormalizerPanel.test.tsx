import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, fireEvent, waitFor } from '@testing-library/react';
import { renderWithProviders } from '@/lib/test-utils';

vi.mock('@/lib/api', () => ({ normalizeMultimodal: vi.fn() }));
vi.mock('@/lib/notification', () => ({ toast: { success: vi.fn(), error: vi.fn(), warning: vi.fn(), info: vi.fn() } }));
vi.mock('@/lib/store', () => ({
  useAppStore: () => null,
}));

import { normalizeMultimodal } from '@/lib/api';
const mockedNormalizeMultimodal = vi.mocked(normalizeMultimodal);
import MultimodalNormalizerPanel from './MultimodalNormalizerPanel';

beforeEach(() => { vi.clearAllMocks(); });

describe('MultimodalNormalizerPanel', () => {
  it('渲染表单', () => {
    renderWithProviders(<MultimodalNormalizerPanel />);
    expect(screen.getByText('多模态标准化')).toBeInTheDocument();
  });

  it('空输入提交显示验证错误', () => {
    renderWithProviders(<MultimodalNormalizerPanel />);
    fireEvent.click(screen.getByText('标准化'));
    expect(screen.getByText(/请至少提供一种模态/)).toBeInTheDocument();
  });

  it('填写文本后提交调用 API', async () => {
    mockedNormalizeMultimodal.mockResolvedValue({
      items: [], primary_text: '文本', has_image: false, modalities: ['text'], textualized: '文本',
    });
    renderWithProviders(<MultimodalNormalizerPanel />);
    const textarea = screen.getByPlaceholderText('输入文本内容...');
    fireEvent.change(textarea, { target: { value: '测试文本' } });
    fireEvent.click(screen.getByText('标准化'));
    await waitFor(() => expect(mockedNormalizeMultimodal).toHaveBeenCalled());
  });

  it('无效 JSON 提交不调用 API', async () => {
    renderWithProviders(<MultimodalNormalizerPanel />);
    const textarea = screen.getByPlaceholderText('输入文本内容...');
    fireEvent.change(textarea, { target: { value: '文本' } });
    const jsonInput = screen.getByPlaceholderText(/key.*value/);
    fireEvent.change(jsonInput, { target: { value: '{bad' } });
    fireEvent.click(screen.getByText('标准化'));
    await waitFor(() => expect(screen.getByText(/JSON/)).toBeInTheDocument());
    expect(mockedNormalizeMultimodal).not.toHaveBeenCalled();
  });
});