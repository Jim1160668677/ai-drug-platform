/**
 * ChatInput 组件单元测试
 *
 * 设计来源：agent-test-case-matrix.md FE-C04~C06
 * 覆盖：输入发送 / Enter 与 Shift+Enter / 长任务进度条
 */
import { describe, it, expect, vi } from 'vitest';
import { render, screen, fireEvent } from '@testing-library/react';
import { ChatInput } from './ChatInput';

const defaultProps = {
  input: '',
  onInputChange: vi.fn(),
  onSend: vi.fn(),
  isSending: false,
};

describe('ChatInput 组件', () => {
  describe('FE-C04 输入并发送', () => {
    it('渲染 textarea 和发送按钮', () => {
      render(<ChatInput {...defaultProps} />);
      expect(screen.getByRole('textbox')).toBeInTheDocument();
      expect(screen.getByRole('button', { name: /发送/ })).toBeInTheDocument();
    });

    it('点击发送按钮调用 onSend', () => {
      const onSend = vi.fn();
      const onInputChange = vi.fn();
      render(
        <ChatInput
          input="测试消息"
          onInputChange={onInputChange}
          onSend={onSend}
          isSending={false}
        />
      );
      fireEvent.click(screen.getByRole('button', { name: /发送/ }));
      expect(onSend).toHaveBeenCalledTimes(1);
    });

    it('空输入时发送按钮禁用', () => {
      render(<ChatInput {...defaultProps} input="" />);
      expect(screen.getByRole('button', { name: /发送/ })).toBeDisabled();
    });

    it('isSending=true 时按钮显示"执行中"且禁用', () => {
      render(<ChatInput {...defaultProps} input="x" isSending={true} />);
      expect(screen.getByRole('button', { name: /执行中/ })).toBeDisabled();
    });

    it('disabled=true 时 textarea 禁用', () => {
      render(<ChatInput {...defaultProps} disabled={true} />);
      expect(screen.getByRole('textbox')).toBeDisabled();
    });
  });

  describe('FE-C05 键盘交互', () => {
    it('Enter 键触发发送', () => {
      const onSend = vi.fn();
      render(
        <ChatInput
          input="测试"
          onInputChange={vi.fn()}
          onSend={onSend}
          isSending={false}
        />
      );
      const textarea = screen.getByRole('textbox');
      fireEvent.keyDown(textarea, { key: 'Enter', shiftKey: false });
      expect(onSend).toHaveBeenCalledTimes(1);
    });

    it('Shift+Enter 不触发发送（换行）', () => {
      const onSend = vi.fn();
      render(
        <ChatInput
          input="测试"
          onInputChange={vi.fn()}
          onSend={onSend}
          isSending={false}
        />
      );
      const textarea = screen.getByRole('textbox');
      fireEvent.keyDown(textarea, { key: 'Enter', shiftKey: true });
      expect(onSend).not.toHaveBeenCalled();
    });

    it('输入触发 onInputChange', () => {
      const onInputChange = vi.fn();
      render(<ChatInput {...defaultProps} onInputChange={onInputChange} />);
      fireEvent.change(screen.getByRole('textbox'), { target: { value: '新内容' } });
      expect(onInputChange).toHaveBeenCalledWith('新内容');
    });
  });

  describe('FE-C06 长任务进度条', () => {
    it('无 taskProgress 时不显示进度条', () => {
      render(<ChatInput {...defaultProps} isSending={true} />);
      expect(screen.queryByText(/步骤/)).not.toBeInTheDocument();
    });

    it('isSending=false 时不显示进度条', () => {
      render(
        <ChatInput
          {...defaultProps}
          isSending={false}
          taskProgress={{ currentStep: 3, maxSteps: 10, durationSec: 15 }}
        />
      );
      expect(screen.queryByText(/步骤/)).not.toBeInTheDocument();
    });

    it('durationSec > 10s 显示进度条', () => {
      render(
        <ChatInput
          {...defaultProps}
          isSending={true}
          taskProgress={{ currentStep: 3, maxSteps: 10, durationSec: 15 }}
        />
      );
      expect(screen.getByText(/步骤 3\/10/)).toBeInTheDocument();
      expect(screen.getByText(/已耗时 15.0s/)).toBeInTheDocument();
    });

    it('currentStep > 0 但 durationSec <= 10s 也显示进度条', () => {
      render(
        <ChatInput
          {...defaultProps}
          isSending={true}
          taskProgress={{ currentStep: 2, maxSteps: 8, durationSec: 5 }}
        />
      );
      expect(screen.getByText(/步骤 2\/8/)).toBeInTheDocument();
    });

    it('进度条宽度按 currentStep/maxSteps 计算', () => {
      const { container } = render(
        <ChatInput
          {...defaultProps}
          isSending={true}
          taskProgress={{ currentStep: 5, maxSteps: 10, durationSec: 12 }}
        />
      );
      const progressBar = container.querySelector('.bg-gradient-to-r');
      expect(progressBar).toBeInTheDocument();
      expect(progressBar?.getAttribute('style')).toContain('width: 50%');
    });
  });

  describe('占位符', () => {
    it('使用自定义 placeholder', () => {
      render(<ChatInput {...defaultProps} placeholder="自定义提示" />);
      expect(screen.getByPlaceholderText('自定义提示')).toBeInTheDocument();
    });

    it('使用默认 placeholder', () => {
      render(<ChatInput {...defaultProps} />);
      expect(
        screen.getByPlaceholderText(/向 Agent 提问/)
      ).toBeInTheDocument();
    });
  });
});
