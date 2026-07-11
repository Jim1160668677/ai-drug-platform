import { create } from 'zustand';

export type NotificationType = 'success' | 'error' | 'warning' | 'info';

export interface Notification {
  id: string;
  type: NotificationType;
  message: string;
  detail?: string;
  duration?: number; // ms, 0 = 不自动关闭
}

interface NotificationState {
  notifications: Notification[];
  showNotification: (n: Omit<Notification, 'id'>) => string;
  dismissNotification: (id: string) => void;
  clearAll: () => void;
}

let counter = 0;

export const useNotificationStore = create<NotificationState>((set) => ({
  notifications: [],
  showNotification: (n) => {
    const id = `notif-${++counter}-${Date.now()}`;
    const notification: Notification = { id, duration: 4000, ...n };
    set((state) => ({
      notifications: [...state.notifications, notification],
    }));

    // 自动关闭
    if (notification.duration && notification.duration > 0) {
      setTimeout(() => {
        set((state) => ({
          notifications: state.notifications.filter((x) => x.id !== id),
        }));
      }, notification.duration);
    }

    return id;
  },
  dismissNotification: (id) =>
    set((state) => ({
      notifications: state.notifications.filter((n) => n.id !== id),
    })),
  clearAll: () => set({ notifications: [] }),
}));

// 便捷辅助函数（可在非组件代码中调用）
export const toast = {
  success: (message: string, detail?: string) =>
    useNotificationStore.getState().showNotification({ type: 'success', message, detail }),
  error: (message: string, detail?: string) =>
    useNotificationStore.getState().showNotification({ type: 'error', message, detail, duration: 6000 }),
  warning: (message: string, detail?: string) =>
    useNotificationStore.getState().showNotification({ type: 'warning', message, detail }),
  info: (message: string, detail?: string) =>
    useNotificationStore.getState().showNotification({ type: 'info', message, detail }),
};
