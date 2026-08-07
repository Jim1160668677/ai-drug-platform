'use client';

/**
 * NoPrefetchLink — 禁用 Next.js RSC 预取的 Link 包装组件
 *
 * 背景：Next.js App Router 默认会在 Link 进入视口/鼠标悬停时
 * 自动发起 RSC 预取请求（形如 `?_rsc=xxxxx`）。在快速切换路由时，
 * 这些预取请求会被取消，浏览器控制台会报 `net::ERR_ABORTED` 错误。
 *
 * 本组件强制 `prefetch={false}`，避免视口/悬停预取，从根上消除此类错误。
 *
 * 用法：在导航场景中用 `<NoPrefetchLink href="...">` 替代 `<Link>`。
 * 注意：点击链接发起的导航请求是必要的，无法避免，那是正常路由行为。
 */

import Link from 'next/link';
import type { ComponentProps } from 'react';

export type NoPrefetchLinkProps = ComponentProps<typeof Link>;

export default function NoPrefetchLink({
  prefetch = false,
  ...rest
}: NoPrefetchLinkProps) {
  return <Link prefetch={prefetch} {...rest} />;
}
