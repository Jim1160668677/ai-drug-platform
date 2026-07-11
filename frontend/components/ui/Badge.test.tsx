import { describe, it, expect } from 'vitest';
import { render, screen } from '@testing-library/react';
import Badge from './Badge';

describe('Badge 组件', () => {
  describe('evidence variant', () => {
    it('GRADE_ 前缀被剥离并显示等级', () => {
      render(<Badge variant="evidence" value="GRADE_I" />);
      expect(screen.getByText('I')).toBeInTheDocument();
    });

    it('LEVEL_ 前缀被剥离并显示等级', () => {
      render(<Badge variant="evidence" value="LEVEL_II" />);
      expect(screen.getByText('II')).toBeInTheDocument();
    });

    it('未知等级回退到 IV 样式但显示原值', () => {
      const { container } = render(<Badge variant="evidence" value="Z" />);
      expect(screen.getByText('Z')).toBeInTheDocument();
      // IV 样式 bg-gray-100
      expect(container.firstChild).toHaveClass('bg-gray-100');
    });
  });

  describe('status variant', () => {
    it('active 状态显示并应用绿色样式', () => {
      const { container } = render(<Badge variant="status" value="active" />);
      expect(screen.getByText('active')).toBeInTheDocument();
      expect(container.firstChild).toHaveClass('bg-green-100');
    });

    it('failed 状态应用红色样式', () => {
      const { container } = render(<Badge variant="status" value="failed" />);
      expect(container.firstChild).toHaveClass('bg-red-100');
    });

    it('未知状态使用默认灰色样式', () => {
      const { container } = render(<Badge variant="status" value="unknown" />);
      expect(container.firstChild).toHaveClass('bg-gray-100');
      expect(screen.getByText('unknown')).toBeInTheDocument();
    });
  });

  describe('role variant', () => {
    it('foundor 角色映射为中文“创始人”', () => {
      render(<Badge variant="role" value="founder" />);
      expect(screen.getByText('创始人')).toBeInTheDocument();
    });

    it('researcher 角色映射为中文“研究员”', () => {
      render(<Badge variant="role" value="researcher" />);
      expect(screen.getByText('研究员')).toBeInTheDocument();
    });

    it('doctor 角色映射为中文“医生”', () => {
      render(<Badge variant="role" value="doctor" />);
      expect(screen.getByText('医生')).toBeInTheDocument();
    });

    it('engineer 角色映射为中文“工程师”', () => {
      render(<Badge variant="role" value="engineer" />);
      expect(screen.getByText('工程师')).toBeInTheDocument();
    });

    it('未知角色显示原值', () => {
      render(<Badge variant="role" value="admin" />);
      expect(screen.getByText('admin')).toBeInTheDocument();
    });
  });

  describe('color variant', () => {
    it('green 颜色应用绿色样式', () => {
      const { container } = render(<Badge variant="green">活跃</Badge>);
      expect(container.firstChild).toHaveClass('bg-green-100');
      expect(container.firstChild).toHaveClass('text-green-800');
      expect(screen.getByText('活跃')).toBeInTheDocument();
    });

    it('red 颜色应用红色样式', () => {
      const { container } = render(<Badge variant="red">高危</Badge>);
      expect(container.firstChild).toHaveClass('bg-red-100');
    });

    it('purple 颜色应用紫色样式', () => {
      const { container } = render(<Badge variant="purple">紫</Badge>);
      expect(container.firstChild).toHaveClass('bg-purple-100');
    });
  });

  describe('children 与 value 优先级', () => {
    it('value 优先于 children', () => {
      render(
        <Badge variant="status" value="active">
          不应显示
        </Badge>
      );
      expect(screen.getByText('active')).toBeInTheDocument();
      expect(screen.queryByText('不应显示')).not.toBeInTheDocument();
    });

    it('未提供 value 时使用 children', () => {
      render(<Badge variant="gray">自定义文本</Badge>);
      expect(screen.getByText('自定义文本')).toBeInTheDocument();
    });
  });

  describe('className 合并', () => {
    it('自定义 className 被合并到样式串', () => {
      const { container } = render(
        <Badge variant="gray" className="ml-2 custom-class">
          X
        </Badge>
      );
      expect(container.firstChild).toHaveClass('ml-2');
      expect(container.firstChild).toHaveClass('custom-class');
      // 仍保留基础类
      expect(container.firstChild).toHaveClass('inline-flex');
      expect(container.firstChild).toHaveClass('rounded');
    });
  });

  describe('基础样式', () => {
    it('始终包含基础类名', () => {
      const { container } = render(<Badge variant="gray">X</Badge>);
      expect(container.firstChild).toHaveClass('inline-flex');
      expect(container.firstChild).toHaveClass('items-center');
      expect(container.firstChild).toHaveClass('px-2');
      expect(container.firstChild).toHaveClass('py-0.5');
      expect(container.firstChild).toHaveClass('rounded');
      expect(container.firstChild).toHaveClass('text-xs');
      expect(container.firstChild).toHaveClass('font-medium');
      expect(container.firstChild).toHaveClass('border');
    });
  });
});
