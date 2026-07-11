import { describe, it, expect } from 'vitest';
import { render, screen } from '@testing-library/react';
import FormError, { FieldLabel } from './FormError';

describe('FormError 组件', () => {
  it('message 为空时返回 null', () => {
    const { container } = render(<FormError message={null} />);
    expect(container.firstChild).toBeNull();
  });

  it('message 为 undefined 时返回 null', () => {
    const { container } = render(<FormError />);
    expect(container.firstChild).toBeNull();
  });

  it('message 为空字符串时返回 null', () => {
    const { container } = render(<FormError message="" />);
    expect(container.firstChild).toBeNull();
  });

  it('渲染 message 文本', () => {
    render(<FormError message="此字段必填" />);
    expect(screen.getByText('此字段必填')).toBeInTheDocument();
  });

  it('包含 AlertCircle 图标（svg）', () => {
    const { container } = render(<FormError message="错误" />);
    expect(container.querySelector('svg')).toBeInTheDocument();
  });

  it('应用红色文本样式', () => {
    const { container } = render(<FormError message="错误" />);
    expect(container.firstChild).toHaveClass('text-red-600');
  });

  it('className 被合并', () => {
    const { container } = render(
      <FormError message="错误" className="mt-4" />
    );
    expect(container.firstChild).toHaveClass('mt-4');
    // 仍保留默认类
    expect(container.firstChild).toHaveClass('text-red-600');
  });
});

describe('FieldLabel 组件', () => {
  it('渲染 children 文本', () => {
    render(<FieldLabel>姓名</FieldLabel>);
    expect(screen.getByText('姓名').tagName).toBe('LABEL');
  });

  it('渲染为 label 元素', () => {
    const { container } = render(<FieldLabel>X</FieldLabel>);
    expect(container.firstChild?.nodeName).toBe('LABEL');
  });

  it('required=true 时显示红色星号', () => {
    const { container } = render(<FieldLabel required>姓名</FieldLabel>);
    // 星号在 .text-red-500 的 span 中
    const star = container.querySelector('.text-red-500');
    expect(star).toBeInTheDocument();
    expect(star?.textContent).toContain('*');
  });

  it('required=false 时不显示星号', () => {
    const { container } = render(<FieldLabel>姓名</FieldLabel>);
    expect(container.querySelector('.text-red-500')).toBeNull();
  });

  it('hint 显示在括号内', () => {
    render(<FieldLabel hint="可选">姓名</FieldLabel>);
    expect(screen.getByText('（可选）')).toBeInTheDocument();
  });

  it('未提供 hint 时不显示括号', () => {
    render(<FieldLabel>姓名</FieldLabel>);
    // 不应出现括号包裹的提示
    expect(document.body.textContent).not.toContain('（');
  });

  it('同时设置 required 与 hint', () => {
    const { container } = render(
      <FieldLabel required hint="5-20 字符">
        用户名
      </FieldLabel>
    );
    expect(screen.getByText('用户名')).toBeInTheDocument();
    // 星号
    const star = container.querySelector('.text-red-500');
    expect(star).toBeInTheDocument();
    expect(star?.textContent).toContain('*');
    // hint 提示（使用模糊匹配，因为括号与文本可能被空白分隔）
    expect(screen.getByText(/5-20 字符/)).toBeInTheDocument();
  });

  it('className 被合并', () => {
    const { container } = render(
      <FieldLabel className="text-blue-500">X</FieldLabel>
    );
    expect(container.firstChild).toHaveClass('text-blue-500');
    expect(container.firstChild).toHaveClass('block');
  });
});
