/**
 * 前端组件测试工具
 *
 * 封装 @testing-library/react 的 render，自动注入 QueryClientProvider，
 * 让依赖 @tanstack/react-query 的组件在测试中无需手动包裹 Provider。
 *
 * 用法：
 *   import { render, screen } from '@/lib/test-utils';
 *   render(<MyComponent />);
 */
import { ReactElement, ReactNode } from 'react';
import { render, RenderOptions } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';

/**
 * 创建测试专用 QueryClient：
 * - retry: 0  避免失败请求重试导致断言时序错乱
 * - gcTime: Infinity  防止 gc 清理缓存造成查询重复触发
 * - staleTime: Infinity  确保数据始终新鲜，便于断言
 */
export function createTestQueryClient(): QueryClient {
  return new QueryClient({
    defaultOptions: {
      queries: {
        retry: false,
        gcTime: Infinity,
        staleTime: Infinity,
        refetchOnWindowFocus: false,
        refetchOnMount: false,
        refetchOnReconnect: false,
      },
      mutations: {
        retry: false,
        gcTime: Infinity,
      },
    },
  });
}

interface WrapperProviderProps {
  children: ReactNode;
}

/** 默认 Provider 包装器（注入 QueryClient） */
export function Wrapper({ children }: WrapperProviderProps) {
  const queryClient = createTestQueryClient();
  return (
    <QueryClientProvider client={queryClient}>{children}</QueryClientProvider>
  );
}

/** 注入自定义 QueryClient 的包装器（便于在测试中访问缓存/设置数据） */
export function createWrapper(queryClient: QueryClient) {
  return function CustomWrapper({ children }: WrapperProviderProps) {
    return (
      <QueryClientProvider client={queryClient}>
        {children}
      </QueryClientProvider>
    );
  };
}

/** 封装 render：自动应用 Wrapper */
export function renderWithProviders(
  ui: ReactElement,
  options?: Omit<RenderOptions, 'wrapper'> & { queryClient?: QueryClient }
) {
  const { queryClient, ...rest } = options || {};
  const client = queryClient ?? createTestQueryClient();
  const wrapper = createWrapper(client);
  const result = render(ui, { wrapper, ...rest });
  return { ...result, queryClient: client };
}

// 默认导出 renderWithProviders，便于按需引用
export default renderWithProviders;
