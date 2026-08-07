'use client';

import { useEffect } from 'react';
import { useRouter } from 'next/navigation';

export default function ChatRedirectPage() {
  const router = useRouter();

  useEffect(() => {
    router.replace('/workbench/intelligence?mode=qa');
  }, [router]);

  return (
    <div className="h-full flex items-center justify-center">
      <div className="text-sm text-gray-500">正在跳转到智能工作台...</div>
    </div>
  );
}
