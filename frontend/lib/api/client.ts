import axios from 'axios';

// 开发环境直连后端（避免 Next.js rewrites 代理 POST body 丢失）
// 生产环境通过 nginx 同源代理，用 /api/v1
const API_BASE = process.env.NEXT_PUBLIC_API_BASE || 'http://localhost:8000/api/v1';

export const api = axios.create({
  baseURL: API_BASE,
  timeout: 60000,
  headers: {
    'Content-Type': 'application/json',
  },
});

// 请求拦截器：注入 JWT
api.interceptors.request.use(
  (config) => {
    if (typeof window !== 'undefined') {
      const token = localStorage.getItem('ai_drug_token');
      if (token) {
        config.headers.Authorization = `Bearer ${token}`;
      }
    }
    return config;
  },
  (error) => Promise.reject(error)
);

// 响应拦截器：信封解包 + 401 跳登录 + 500 提示
api.interceptors.response.use(
  (response) => {
    const payload = response.data;
    if (
      payload &&
      typeof payload === 'object' &&
      payload.success === true &&
      'data' in payload
    ) {
      response.data = payload.data;
    }
    return response;
  },
  (error) => {
    if (error.code === 'ERR_ABORTED' || error.code === 'ECONNABORTED') {
      console.warn('[API] 请求被中止/超时:', error.config?.url);
      return Promise.reject(error);
    }
    if (error.response) {
      const { status, data } = error.response;
      if (status === 401 && typeof window !== 'undefined') {
        localStorage.removeItem('ai_drug_token');
        localStorage.removeItem('ai_drug_user');
        if (window.location.pathname !== '/') {
          window.history.replaceState(null, '', '/');
          window.dispatchEvent(new PopStateEvent('popstate'));
        }
      } else if (status >= 500) {
        console.error('[API Error]', status, data);
      }
    } else if (error.code === 'ERR_NETWORK' || error.message?.includes('Network Error')) {
      console.error('[API] 网络错误：后端服务可能未启动', error.message);
    }
    return Promise.reject(error);
  }
);

export default api;
