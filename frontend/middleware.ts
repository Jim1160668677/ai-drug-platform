// Auth middleware — handles route protection with RSC-aware redirects
import { NextResponse } from 'next/server';
import type { NextRequest } from 'next/server';

const TOKEN_COOKIE = 'ai_drug_token';
const PROTECTED_PREFIXES = ['/workbench', '/dashboard', '/admin'];
const PUBLIC_PATHS = ['/', '/login', '/register', '/favicon.ico'];

export function middleware(request: NextRequest) {
  const { pathname, search } = request.nextUrl;

  if (PUBLIC_PATHS.includes(pathname)) {
    return NextResponse.next();
  }

  const isProtected = PROTECTED_PREFIXES.some(
    (prefix) => pathname === prefix || pathname.startsWith(prefix + '/')
  );

  if (!isProtected) {
    return NextResponse.next();
  }

  const token = request.cookies.get(TOKEN_COOKIE)?.value;

  if (!token) {
    // RSC 请求检测：
    // - ?_rsc= 查询参数（Next.js 客户端导航）
    // - RSC: 1 头部
    // - x-nextjs-data 头部（Next.js 数据请求）
    // - Next-Router-State-Tree 头部（路由状态树）
    // - Accept: text/x-component（RSC 内容类型）
    // 任一匹配即视为 RSC 请求，直接放行避免 307 redirect
    // 导致浏览器 fetchServerResponse 中止 (net::ERR_ABORTED)。
    // 客户端 Providers 组件会检测未登录状态并跳转到首页。
    const hasRscQuery = search.includes('_rsc') || request.nextUrl.searchParams.has('_rsc');
    const hasRscHeader =
      request.headers.get('RSC') === '1' ||
      request.headers.get('x-nextjs-data') !== null ||
      request.headers.get('next-router-state-tree') !== null;
    const accept = request.headers.get('accept') || '';
    const hasRscAccept = accept.includes('text/x-component');

    if (hasRscQuery || hasRscHeader || hasRscAccept) {
      return NextResponse.next();
    }

    const url = request.nextUrl.clone();
    url.pathname = '/';
    url.search = '';
    return NextResponse.redirect(url);
  }

  return NextResponse.next();
}

export const config = {
  matcher: ['/workbench/:path*', '/dashboard/:path*', '/admin/:path*', '/'],
};
