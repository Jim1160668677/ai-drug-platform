'use client';

import { AlertCircle } from 'lucide-react';
import clsx from 'clsx';

interface FormErrorProps {
  message?: string | null;
  className?: string;
}

export default function FormError({ message, className }: FormErrorProps) {
  if (!message) return null;
  return (
    <div className={clsx('flex items-center gap-1 mt-1 text-xs text-red-600', className)}>
      <AlertCircle className="w-3 h-3 shrink-0" />
      <span>{message}</span>
    </div>
  );
}

interface FieldLabelProps {
  children: React.ReactNode;
  required?: boolean;
  hint?: string;
  className?: string;
}

export function FieldLabel({ children, required, hint, className }: FieldLabelProps) {
  return (
    <label className={clsx('block text-xs font-medium text-gray-700 mb-1', className)}>
      {children}
      {required && <span className="text-red-500"> *</span>}
      {hint && <span className="ml-1 text-gray-400 font-normal">（{hint}）</span>}
    </label>
  );
}
