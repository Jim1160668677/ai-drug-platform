'use client';

import { clsx } from 'clsx';
import { Inbox, Search, FolderOpen, CheckCircle2 } from 'lucide-react';
import type { ComponentType, ReactNode } from 'react';

type EmptyStateType =
  | 'default'
  | 'no-data'
  | 'no-results'
  | 'completed'
  | 'error';

type IconType = ComponentType<{ className?: string }>;

const DEFAULT_ICONS: Record<EmptyStateType, IconType> = {
  default: Inbox,
  'no-data': FolderOpen,
  'no-results': Search,
  completed: CheckCircle2,
  error: Inbox,
};

interface EmptyStateProps {
  type?: EmptyStateType;
  icon?: IconType;
  title: string;
  description?: string;
  action?: ReactNode;
  className?: string;
  iconSize?: 'sm' | 'md' | 'lg';
}

const SIZE_MAP: Record<string, string> = {
  sm: 'w-8 h-8',
  md: 'w-12 h-12',
  lg: 'w-16 h-16',
};

export default function EmptyState({
  type = 'default',
  icon: CustomIcon,
  title,
  description,
  action,
  className,
  iconSize = 'md',
}: EmptyStateProps) {
  const Icon = CustomIcon || DEFAULT_ICONS[type];
  const iconColor =
    type === 'error'
      ? 'text-red-300'
      : type === 'completed'
      ? 'text-green-300'
      : 'text-gray-300';

  return (
    <div
      className={clsx(
        'flex flex-col items-center justify-center text-center py-12 px-4',
        className
      )}
      role="status"
      aria-live="polite"
    >
      <Icon className={clsx(SIZE_MAP[iconSize], iconColor, 'mb-4')} />
      <h3 className="text-sm font-medium text-gray-700">{title}</h3>
      {description && (
        <p className="mt-2 text-sm text-gray-500 max-w-sm">{description}</p>
      )}
      {action && <div className="mt-4">{action}</div>}
    </div>
  );
}

export function EmptyListState({
  title = '\u6682\u65e0\u6570\u636e',
  description,
  action,
  className,
}: {
  title?: string;
  description?: string;
  action?: ReactNode;
  className?: string;
}) {
  return (
    <EmptyState
      type="no-data"
      title={title}
      description={description}
      action={action}
      className={className}
    />
  );
}
