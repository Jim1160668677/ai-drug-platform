'use client';

import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { useEffect, useState } from 'react';
import ErrorBoundary from '@/components/ui/ErrorBoundary';
import ToastContainer from '@/components/ui/Toast';
import { useAppStore } from '@/lib/store';

export default function Providers({ children }: { children: React.ReactNode }) {
  const [queryClient] = useState(
    () =>
      new QueryClient({
        defaultOptions: {
          queries: {
            refetchOnWindowFocus: false,
            retry: 1,
          },
          mutations: {
            onError: (err) => {
              const message = err instanceof Error ? err.message : '操作失败';
              import('@/lib/notification').then(({ toast }) => {
                toast.error('请求失败', message);
              });
            },
          },
        },
      })
  );

  useEffect(() => {
    useAppStore.persist.rehydrate();
  }, []);

  return (
    <QueryClientProvider client={queryClient}>
      <ErrorBoundary>
        {children}
        <ToastContainer />
      </ErrorBoundary>
    </QueryClientProvider>
  );
}
