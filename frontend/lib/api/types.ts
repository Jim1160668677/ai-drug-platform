// 通用响应类型定义

/** 后端信封响应（响应拦截器已解包，业务代码通常直接拿 data） */
export interface ApiResponse<T = unknown> {
  success: boolean;
  data: T;
  meta?: {
    page?: number;
    page_size?: number;
    total?: number;
  };
}

/** 分页响应 */
export interface PagedResponse<T> {
  items: T[];
  total: number;
  page: number;
  page_size: number;
}

/** 错误响应 */
export interface ErrorResponse {
  detail: string;
  status_code: number;
}

/** 信封消息响应（StandardResponse） */
export interface StandardResponse<T = unknown> {
  message: string;
  data: T;
}
