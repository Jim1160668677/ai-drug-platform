'use client';

import { useEffect, useState } from 'react';

/**
 * useMediaQuery — 响应式断点 Hook
 *
 * 设计来源：2026-07-18-agent-functional-design.md §4.3
 *
 * 断点规格：
 * - <768px：移动端（单栏 + 全屏抽屉）
 * - 768-1279px：平板/小笔记本（两栏 + 浮层抽屉）
 * - ≥1280px：桌面（三栏并列）
 *
 * SSR 安全：首次渲染返回 false（避免水合不匹配），挂载后立即同步真实值。
 */
export function useMediaQuery(query: string): boolean {
  const [matches, setMatches] = useState(false);

  useEffect(() => {
    if (typeof window === 'undefined' || !window.matchMedia) return;
    const mql = window.matchMedia(query);
    // 同步当前值
    setMatches(mql.matches);
    const handler = (e: MediaQueryListEvent) => setMatches(e.matches);
    // addEventListener 在现代浏览器优先；旧 Safari 用 addListener
    if (mql.addEventListener) {
      mql.addEventListener('change', handler);
      return () => mql.removeEventListener('change', handler);
    } else {
      // Safari < 14 兼容
      // @ts-expect-error legacy API
      mql.addListener(handler);
      return () => {
        // @ts-expect-error legacy API
        mql.removeListener(handler);
      };
    }
  }, [query]);

  return matches;
}

/**
 * 三栏布局断点 Hook — 一站式返回三栏布局所需断点状态
 *
 * - isMobile: <768px
 * - isTablet: 768-1279px
 * - isDesktop: ≥1280px
 */
export function useResponsiveLayout() {
  const isDesktop = useMediaQuery('(min-width: 1280px)');
  const isTablet = useMediaQuery('(min-width: 768px) and (max-width: 1279.98px)');
  const isMobile = useMediaQuery('(max-width: 767.98px)');

  return { isDesktop, isTablet, isMobile };
}
