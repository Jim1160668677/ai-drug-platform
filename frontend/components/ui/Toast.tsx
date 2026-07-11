'use client';

import { useEffect } from 'react';
import { CheckCircle, XCircle, AlertTriangle, Info, X } from 'lucide-react';
import clsx from 'clsx';
import { useNotificationStore, NotificationType } from '@/lib/notification';

const ICONS: Record<NotificationType, typeof CheckCircle> = {
  success: CheckCircle,
  error: XCircle,
  warning: AlertTriangle,
  info: Info,
};

const STYLES: Record<NotificationType, string> = {
  success: 'bg-green-50 border-green-200 text-green-800',
  error: 'bg-red-50 border-red-200 text-red-800',
  warning: 'bg-amber-50 border-amber-200 text-amber-800',
  info: 'bg-blue-50 border-blue-200 text-blue-800',
};

const ICON_COLORS: Record<NotificationType, string> = {
  success: 'text-green-500',
  error: 'text-red-500',
  warning: 'text-amber-500',
  info: 'text-blue-500',
};

export default function ToastContainer() {
  const { notifications, dismissNotification } = useNotificationStore();

  return (
    <div className="fixed top-4 right-4 z-[9999] flex flex-col gap-2 max-w-md w-full pointer-events-none">
      {notifications.map((n) => {
        const Icon = ICONS[n.type];
        return (
          <div
            key={n.id}
            className={clsx(
              'flex items-start gap-3 p-3 rounded-lg border shadow-md pointer-events-auto',
              'animate-in slide-in-from-right duration-200',
              STYLES[n.type]
            )}
          >
            <Icon className={clsx('w-5 h-5 shrink-0 mt-0.5', ICON_COLORS[n.type])} />
            <div className="flex-1 min-w-0">
              <div className="text-sm font-medium">{n.message}</div>
              {n.detail && (
                <div className="text-xs mt-1 opacity-80 break-words">{n.detail}</div>
              )}
            </div>
            <button
              onClick={() => dismissNotification(n.id)}
              className="shrink-0 opacity-60 hover:opacity-100"
            >
              <X className="w-4 h-4" />
            </button>
          </div>
        );
      })}
    </div>
  );
}
