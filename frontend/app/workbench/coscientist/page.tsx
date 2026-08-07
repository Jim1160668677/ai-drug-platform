'use client';

import { useEffect } from 'react';
import { useRouter } from 'next/navigation';

export default function CoScientistRedirectPage() {
  const router = useRouter();

  useEffect(() => {
    router.replace('/workbench/intelligence?mode=coscientist');
  }, [router]);

  return (
    <div className="h-full flex items-center justify-center">
      <div className="text-sm text-gray-500">正在跳转到 Co-Scientist 科学推理引擎...</div>
    </div>
  );
}
