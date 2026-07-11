'use client';

import { Loader2 } from 'lucide-react';
import { clsx } from 'clsx';

type LoadingSize = 'sm' | 'md' | 'lg';

interface LoadingProps {
  size?: LoadingSize;
  label?: string;
  className?: string;
  fullscreen?: boolean;
}

const sizeMap: Record<LoadingSize, string> = {
  sm: 'h-4 w-4',
  md: 'h-6 w-6',
  lg: 'h-10 w-10',
};

export default function Loading({
  size = 'md',
  label,
  className,
  fullscreen = false,
}: LoadingProps) {
  const spinner = (
    <div className={clsx('flex flex-col items-center justify-center gap-3', className)}>
      <Loader2 className={clsx(sizeMap[size], 'animate-spin text-primary-600')} />
      {label && <p className="text-sm text-gray-500">{label}</p>}
    </div>
  );

  if (fullscreen) {
    return (
      <div className="fixed inset-0 z-50 flex items-center justify-center bg-white/80 backdrop-blur-sm">
        {spinner}
      </div>
    );
  }

  return spinner;
}

export function LoadingRow({ cols = 5 }: { cols?: number }) {
  return (
    <tr>
      {Array.from({ length: cols }).map((_, i) => (
        <td key={i} className="px-4 py-3">
          <div className="h-4 w-full animate-pulse rounded bg-gray-200" />
        </td>
      ))}
    </tr>
  );
}

export function LoadingCard() {
  return (
    <div className="rounded-xl border border-gray-200 bg-white p-5 shadow-sm">
      <div className="h-5 w-1/3 animate-pulse rounded bg-gray-200" />
      <div className="mt-4 h-8 w-1/2 animate-pulse rounded bg-gray-200" />
      <div className="mt-3 h-3 w-full animate-pulse rounded bg-gray-100" />
      <div className="mt-2 h-3 w-2/3 animate-pulse rounded bg-gray-100" />
    </div>
  );
}
