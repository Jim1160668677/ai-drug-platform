import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { render, screen, fireEvent } from '@testing-library/react';
import React from 'react';
import ErrorBoundary from './ErrorBoundary';
import { useNotificationStore } from '@/lib/notification';

// 制造一个会抛错的子组件
function ThrowComponent({ message = '故意抛错' }: { message?: string }) {
  throw new Error(message);
}

// 不抛错的子组件
function OkComponent() {
  return <div data-testid="ok">正常内容</div>;
}

describe('ErrorBoundary 组件', () => {
  let consoleErrorSpy: ReturnType<typeof vi.spyOn>;

  beforeEach(() => {
    // 抑制 React error boundary 的 console.error 噪音
    consoleErrorSpy = vi.spyOn(console, 'error').mockImplementation(() => {});
    // 清空通知 store（ErrorBoundary.componentDidCatch 会调用 toast.error）
    useNotificationStore.getState().clearAll();
  });

  afterEach(() => {
    consoleErrorSpy.mockRestore();
    useNotificationStore.getState().clearAll();
  });

  it('无错误时渲染 children', () => {
    render(
      <ErrorBoundary>
        <OkComponent />
      </ErrorBoundary>
    );
    expect(screen.getByTestId('ok')).toBeInTheDocument();
  });

  it('子组件抛错时渲染默认 fallback', () => {
    render(
      <ErrorBoundary>
        <ThrowComponent message="测试异常" />
      </ErrorBoundary>
    );
    expect(screen.getByText('渲染异常')).toBeInTheDocument();
    expect(screen.getByText('测试异常')).toBeInTheDocument();
  });

  it('默认 fallback 包含“重试”按钮', () => {
    render(
      <ErrorBoundary>
        <ThrowComponent />
      </ErrorBoundary>
    );
    expect(screen.getByText('重试')).toBeInTheDocument();
  });

  it('点击“重试”按钮清空错误状态', () => {
    // 重试后会重新渲染 children；ThrowComponent 仍会抛错，
    // 所以这里用可控的子组件验证 reset 行为
    let shouldThrow = true;
    function ToggleThrow() {
      if (shouldThrow) throw new Error('toggle');
      return <div data-testid="recovered">已恢复</div>;
    }

    render(
      <ErrorBoundary>
        <ToggleThrow />
      </ErrorBoundary>
    );
    expect(screen.getByText('渲染异常')).toBeInTheDocument();

    // 关闭抛错，再点重试
    shouldThrow = false;
    fireEvent.click(screen.getByText('重试'));
    expect(screen.getByTestId('recovered')).toBeInTheDocument();
  });

  it('支持自定义 fallback 渲染函数', () => {
    render(
      <ErrorBoundary
        fallback={(err, reset) => (
          <div>
            <span data-testid="custom-msg">{err.message}</span>
            <button onClick={reset} data-testid="custom-reset">
              自定义重试
            </button>
          </div>
        )}
      >
        <ThrowComponent message="自定义错误" />
      </ErrorBoundary>
    );
    expect(screen.getByTestId('custom-msg')).toHaveTextContent('自定义错误');
    expect(screen.getByTestId('custom-reset')).toBeInTheDocument();
    // 不应显示默认 fallback
    expect(screen.queryByText('渲染异常')).toBeNull();
  });

  it('自定义 fallback 的 reset 函数可用', () => {
    let shouldThrow = true;
    function ToggleThrow() {
      if (shouldThrow) throw new Error('t');
      return <div data-testid="ok">OK</div>;
    }

    render(
      <ErrorBoundary
        fallback={(err, reset) => (
          <button onClick={reset} data-testid="r">
            重试
          </button>
        )}
      >
        <ToggleThrow />
      </ErrorBoundary>
    );
    shouldThrow = false;
    fireEvent.click(screen.getByTestId('r'));
    expect(screen.getByTestId('ok')).toBeInTheDocument();
  });

  it('子组件抛错时调用 onError 回调', () => {
    const onError = vi.fn();
    render(
      <ErrorBoundary onError={onError}>
        <ThrowComponent message="回调测试" />
      </ErrorBoundary>
    );
    expect(onError).toHaveBeenCalledTimes(1);
    const [err] = onError.mock.calls[0];
    expect(err).toBeInstanceOf(Error);
    expect(err.message).toBe('回调测试');
  });

  it('无错误时不调用 onError', () => {
    const onError = vi.fn();
    render(
      <ErrorBoundary onError={onError}>
        <OkComponent />
      </ErrorBoundary>
    );
    expect(onError).not.toHaveBeenCalled();
  });
});
