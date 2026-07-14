'use client';

import { useEffect } from 'react';
import { AlertTriangle, RefreshCw } from 'lucide-react';

export default function Error({
  error,
  reset,
}: {
  error: Error & { digest?: string };
  reset: () => void;
}) {
  useEffect(() => {
    console.error('[Workbench Error]', error);
  }, [error]);

  return (
    <div className="min-h-[400px] flex items-center justify-center p-6">
      <div className="max-w-md w-full bg-white border border-red-200 rounded-lg shadow-sm p-6">
        <div className="flex items-start gap-3">
          <AlertTriangle className="w-6 h-6 text-red-500 shrink-0 mt-0.5" />
          <div className="flex-1 min-w-0">
            <h2 className="text-base font-semibold text-gray-900">页面加载失败</h2>
            <p className="text-xs text-gray-500 mt-1 break-all">
              {error.message || '页面渲染时发生错误'}
            </p>
            <button
              onClick={reset}
              className="mt-4 inline-flex items-center gap-1.5 px-3 py-1.5 text-xs font-medium text-white bg-blue-600 hover:bg-blue-700 rounded transition-colors"
            >
              <RefreshCw className="w-3.5 h-3.5" />
              重试
            </button>
          </div>
        </div>
      </div>
    </div>
  );
}
