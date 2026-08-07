'use client';

import { clsx } from 'clsx';

interface SkeletonProps {
  className?: string;
  /** 圆形骨架 */
  circle?: boolean;
}

/**
 * Skeleton — 基础骨架屏原子组件
 *
 * 用于在数据加载时显示占位动画，避免空白闪烁。
 * 配合 SkeletonText / SkeletonRow / SkeletonCard 组合使用。
 */
export default function Skeleton({ className, circle = false }: SkeletonProps) {
  return (
    <div
      className={clsx(
        'animate-pulse bg-gray-200',
        circle ? 'rounded-full' : 'rounded',
        className
      )}
      aria-hidden="true"
    />
  );
}

/**
 * SkeletonText — 文本骨架屏
 *
 * 模拟多行文本加载状态。
 */
export function SkeletonText({
  lines = 3,
  className,
  lineHeight = 'h-3',
}: {
  lines?: number;
  className?: string;
  lineHeight?: string;
}) {
  return (
    <div className={clsx('space-y-2', className)} aria-hidden="true">
      {Array.from({ length: lines }).map((_, i) => (
        <Skeleton
          key={i}
          className={clsx(lineHeight, i === lines - 1 ? 'w-2/3' : 'w-full')}
        />
      ))}
    </div>
  );
}

/**
 * SkeletonRow — 表格行骨架屏
 */
export function SkeletonRow({ cols = 5 }: { cols?: number }) {
  return (
    <tr aria-hidden="true">
      {Array.from({ length: cols }).map((_, i) => (
        <td key={i} className="px-4 py-3">
          <Skeleton className="h-4 w-full" />
        </td>
      ))}
    </tr>
  );
}

/**
 * SkeletonCard — 卡片骨架屏
 *
 * 用于网格/卡片列表的加载占位。
 */
export function SkeletonCard() {
  return (
    <div className="rounded-xl border border-gray-200 bg-white p-5 shadow-sm" aria-hidden="true">
      <Skeleton className="h-5 w-1/3" />
      <Skeleton className="mt-4 h-8 w-1/2" />
      <Skeleton className="mt-3 h-3 w-full" />
      <Skeleton className="mt-2 h-3 w-2/3" />
    </div>
  );
}

/**
 * SkeletonList — 列表骨架屏
 *
 * 用于列表/表格的加载占位。
 */
export function SkeletonList({ count = 3 }: { count?: number }) {
  return (
    <div className="space-y-3" aria-hidden="true">
      {Array.from({ length: count }).map((_, i) => (
        <div key={i} className="flex items-center gap-3 p-3 border border-gray-200 rounded-lg">
          <Skeleton circle className="w-10 h-10" />
          <div className="flex-1 space-y-2">
            <Skeleton className="h-4 w-1/4" />
            <Skeleton className="h-3 w-1/2" />
          </div>
        </div>
      ))}
    </div>
  );
}
