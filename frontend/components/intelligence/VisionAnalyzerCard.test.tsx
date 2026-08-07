import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, fireEvent, waitFor } from '@testing-library/react';
import { renderWithProviders } from '@/lib/test-utils';

vi.mock('@/lib/api', () => ({ analyzeVision: vi.fn() }));
vi.mock('@/lib/notification', () => ({ toast: { success: vi.fn(), error: vi.fn(), warning: vi.fn(), info: vi.fn() } }));
vi.mock('@/lib/store', () => ({
  useAppStore: () => null,
}));

import { analyzeVision } from '@/lib/api';
const mockedAnalyzeVision = vi.mocked(analyzeVision);
import VisionAnalyzerCard from './VisionAnalyzerCard';

beforeEach(() => { vi.clearAllMocks(); });

describe('VisionAnalyzerCard', () => {
  it('渲染表单', () => {
    renderWithProviders(<VisionAnalyzerCard />);
    expect(screen.getByText('视觉内容解析')).toBeInTheDocument();
  });

  it('空表单提交显示验证错误', () => {
    renderWithProviders(<VisionAnalyzerCard />);
    fireEvent.click(screen.getByText('解析图片'));
    expect(screen.getByText('请输入图片 data URI')).toBeInTheDocument();
  });

  it('有图片无提示词显示验证错误', () => {
    renderWithProviders(<VisionAnalyzerCard />);
    const uriInput = screen.getByPlaceholderText(/data:image/);
    fireEvent.change(uriInput, { target: { value: 'data:image/png;base64,abc' } });
    fireEvent.click(screen.getByText('解析图片'));
    expect(screen.getByText('请输入解析提示词')).toBeInTheDocument();
  });

  it('完整输入提交调用 API', async () => {
    mockedAnalyzeVision.mockResolvedValue({
      description: '描述', model: 'vision-1', usage: {}, cost_usd: 0.01, duration_sec: 2,
    });
    renderWithProviders(<VisionAnalyzerCard />);
    fireEvent.change(screen.getByPlaceholderText(/data:image/), { target: { value: 'data:image/png;base64,abc' } });
    fireEvent.change(screen.getByPlaceholderText(/病理切片/), { target: { value: '描述图片' } });
    fireEvent.click(screen.getByText('解析图片'));
    await waitFor(() => expect(mockedAnalyzeVision).toHaveBeenCalled());
  });
});