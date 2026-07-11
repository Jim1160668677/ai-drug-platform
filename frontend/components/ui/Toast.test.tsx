import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest';
import { render, screen, fireEvent } from '@testing-library/react';
import ToastContainer from './Toast';
import { useNotificationStore } from '@/lib/notification';

describe('ToastContainer 组件', () => {
  beforeEach(() => {
    useNotificationStore.getState().clearAll();
    vi.useFakeTimers();
  });

  afterEach(() => {
    vi.useRealTimers();
  });

  it('无通知时不渲染任何通知项', () => {
    const { container } = render(<ToastContainer />);
    // 容器存在但内部无通知卡片（无消息文本）
    expect(container.querySelector('.pointer-events-auto')).toBeNull();
  });

  it('渲染通知消息', () => {
    useNotificationStore.getState().showNotification({
      type: 'success',
      message: '保存成功',
      duration: 0,
    });
    render(<ToastContainer />);
    expect(screen.getByText('保存成功')).toBeInTheDocument();
  });

  it('渲染通知详情', () => {
    useNotificationStore.getState().showNotification({
      type: 'error',
      message: '失败',
      detail: '数据库连接超时',
      duration: 0,
    });
    render(<ToastContainer />);
    expect(screen.getByText('失败')).toBeInTheDocument();
    expect(screen.getByText('数据库连接超时')).toBeInTheDocument();
  });

  it('点击关闭按钮移除通知', () => {
    useNotificationStore.getState().showNotification({
      type: 'info',
      message: '提示',
      duration: 0,
    });
    render(<ToastContainer />);
    expect(screen.getByText('提示')).toBeInTheDocument();
    // 关闭按钮是包含 X 图标的 button
    const closeBtn = screen.getByRole('button');
    fireEvent.click(closeBtn);
    expect(screen.queryByText('提示')).toBeNull();
  });

  it('同时渲染多条通知', () => {
    useNotificationStore.getState().showNotification({ type: 'info', message: 'A', duration: 0 });
    useNotificationStore.getState().showNotification({ type: 'info', message: 'B', duration: 0 });
    useNotificationStore.getState().showNotification({ type: 'info', message: 'C', duration: 0 });
    render(<ToastContainer />);
    expect(screen.getByText('A')).toBeInTheDocument();
    expect(screen.getByText('B')).toBeInTheDocument();
    expect(screen.getByText('C')).toBeInTheDocument();
  });

  it('渲染通知时包含 svg 图标', () => {
    useNotificationStore.getState().showNotification({
      type: 'success',
      message: '成功',
      duration: 0,
    });
    const { container } = render(<ToastContainer />);
    // 至少有 2 个 svg：类型图标 + 关闭按钮的 X 图标
    const svgs = container.querySelectorAll('svg');
    expect(svgs.length).toBeGreaterThanOrEqual(2);
  });

  it('success 类型应用绿色背景样式', () => {
    useNotificationStore.getState().showNotification({
      type: 'success',
      message: 'OK',
      duration: 0,
    });
    const { container } = render(<ToastContainer />);
    // 通知卡片应有 bg-green-50
    const card = container.querySelector('.bg-green-50');
    expect(card).toBeInTheDocument();
  });

  it('error 类型应用红色背景样式', () => {
    useNotificationStore.getState().showNotification({
      type: 'error',
      message: 'ERR',
      duration: 0,
    });
    const { container } = render(<ToastContainer />);
    const card = container.querySelector('.bg-red-50');
    expect(card).toBeInTheDocument();
  });

  it('warning 类型应用黄色背景样式', () => {
    useNotificationStore.getState().showNotification({
      type: 'warning',
      message: 'WARN',
      duration: 0,
    });
    const { container } = render(<ToastContainer />);
    const card = container.querySelector('.bg-amber-50');
    expect(card).toBeInTheDocument();
  });

  it('info 类型应用蓝色背景样式', () => {
    useNotificationStore.getState().showNotification({
      type: 'info',
      message: 'INFO',
      duration: 0,
    });
    const { container } = render(<ToastContainer />);
    const card = container.querySelector('.bg-blue-50');
    expect(card).toBeInTheDocument();
  });

  it('通知数量与 store 状态同步', () => {
    useNotificationStore.getState().showNotification({ type: 'info', message: 'A', duration: 0 });
    useNotificationStore.getState().showNotification({ type: 'info', message: 'B', duration: 0 });
    const { container } = render(<ToastContainer />);
    // 应有 2 个关闭按钮（每条通知一个）
    const closeBtns = container.querySelectorAll('button');
    expect(closeBtns).toHaveLength(2);
  });
});
