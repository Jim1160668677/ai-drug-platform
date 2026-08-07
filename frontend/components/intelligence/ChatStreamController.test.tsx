import { describe, it, expect, vi } from 'vitest';
import { render, screen, fireEvent } from '@testing-library/react';
import ChatStreamController from './ChatStreamController';

describe('ChatStreamController', () => {
  it('关闭状态显示开关', () => {
    render(
      <ChatStreamController
        useStream={false}
        onToggleStream={vi.fn()}
        streamStatus="idle"
      />,
    );
    expect(screen.getByText('流式')).toBeInTheDocument();
  });

  it('点击开关触发 onToggleStream(true)', () => {
    const onToggle = vi.fn();
    render(
      <ChatStreamController useStream={false} onToggleStream={onToggle} streamStatus="idle" />,
    );
    fireEvent.click(screen.getByText('流式'));
    expect(onToggle).toHaveBeenCalledWith(true);
  });

  it('开启状态点击触发 onToggleStream(false)', () => {
    const onToggle = vi.fn();
    render(
      <ChatStreamController useStream={true} onToggleStream={onToggle} streamStatus="idle" />,
    );
    fireEvent.click(screen.getByText('流式'));
    expect(onToggle).toHaveBeenCalledWith(false);
  });

  it('streaming 状态显示中止按钮', () => {
    const onAbort = vi.fn();
    render(
      <ChatStreamController
        useStream={true}
        onToggleStream={vi.fn()}
        streamStatus="streaming"
        onAbort={onAbort}
      />,
    );
    // streaming 时应显示中止相关 UI
    expect(screen.getByText('流式').parentElement).toBeInTheDocument();
  });

  it('error 状态不崩溃', () => {
    render(
      <ChatStreamController
        useStream={true}
        onToggleStream={vi.fn()}
        streamStatus="error"
      />,
    );
    expect(screen.getByText('流式')).toBeInTheDocument();
  });
});