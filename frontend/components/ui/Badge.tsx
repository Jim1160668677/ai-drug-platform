import clsx from 'clsx';
import { ReactNode } from 'react';

type Variant = 'evidence' | 'status' | 'role' | 'green' | 'blue' | 'gray' | 'red' | 'yellow' | 'purple';

const EVIDENCE_STYLES: Record<string, string> = {
  I: 'bg-green-100 text-green-800 border-green-200',
  II: 'bg-blue-100 text-blue-800 border-blue-200',
  III: 'bg-yellow-100 text-yellow-800 border-yellow-200',
  IV: 'bg-gray-100 text-gray-800 border-gray-200',
};

const STATUS_STYLES: Record<string, string> = {
  active: 'bg-green-100 text-green-800',
  paused: 'bg-yellow-100 text-yellow-800',
  completed: 'bg-blue-100 text-blue-800',
  archived: 'bg-gray-100 text-gray-800',
  failed: 'bg-red-100 text-red-800',
  planned: 'bg-gray-100 text-gray-700',
  running: 'bg-blue-100 text-blue-800',
};

const ROLE_LABELS: Record<string, string> = {
  founder: '创始人',
  chief: '首席',
  researcher: '研究员',
  doctor: '医生',
  engineer: '工程师',
};

const ROLE_STYLES: Record<string, string> = {
  founder: 'bg-purple-100 text-purple-800',
  chief: 'bg-indigo-100 text-indigo-800',
  researcher: 'bg-blue-100 text-blue-800',
  doctor: 'bg-emerald-100 text-emerald-800',
  engineer: 'bg-amber-100 text-amber-800',
};

const COLOR_STYLES: Record<string, string> = {
  green: 'bg-green-100 text-green-800 border-green-200',
  blue: 'bg-blue-100 text-blue-800 border-blue-200',
  gray: 'bg-gray-100 text-gray-800 border-gray-200',
  red: 'bg-red-100 text-red-800 border-red-200',
  yellow: 'bg-yellow-100 text-yellow-800 border-yellow-200',
  purple: 'bg-purple-100 text-purple-800 border-purple-200',
};

interface BadgeProps {
  variant: Variant;
  value?: string;
  className?: string;
  children?: ReactNode;
}

export default function Badge({ variant, value, className, children }: BadgeProps) {
  let style = '';
  let label = value ?? children;

  if (variant === 'evidence') {
    const grade = (value ?? '').replace('GRADE_', '').replace('LEVEL_', '');
    style = EVIDENCE_STYLES[grade] || EVIDENCE_STYLES.IV;
    label = grade;
  } else if (variant === 'status') {
    style = STATUS_STYLES[value ?? ''] || 'bg-gray-100 text-gray-800';
  } else if (variant === 'role') {
    style = ROLE_STYLES[value ?? ''] || 'bg-gray-100 text-gray-800';
    label = ROLE_LABELS[value ?? ''] || value;
  } else if (variant in COLOR_STYLES) {
    style = COLOR_STYLES[variant];
  }

  return (
    <span
      className={clsx(
        'inline-flex items-center px-2 py-0.5 rounded text-xs font-medium border',
        style,
        className
      )}
    >
      {label}
    </span>
  );
}
