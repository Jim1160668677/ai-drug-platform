import { describe, it, expect, beforeEach, vi } from 'vitest';

// 注意：lib/auth.ts 顶层 import { login as apiLogin } from './api'，
// api.ts 顶层创建 axios 实例并访问 process.env.NEXT_PUBLIC_API_BASE。
// 我们 mock './api' 模块，避免真实 axios 实例。
vi.mock('./api', () => ({
  login: vi.fn(() => Promise.resolve({ access_token: 'tok', role: 'researcher', name: 'U', email: 'u@e.com' })),
}));

import { login, logout, getToken, getCurrentUser, isLoggedIn, AuthUser } from './auth';
import { login as apiLogin } from './api';

const TOKEN_KEY = 'ai_drug_token';
const USER_KEY = 'ai_drug_user';

describe('auth 模块', () => {
  beforeEach(() => {
    window.localStorage.clear();
    vi.clearAllMocks();
  });

  describe('login', () => {
    it('调用 api 并将 token 与 user 写入 localStorage', async () => {
      const user = await login('u@e.com', 'pw');
      expect(apiLogin).toHaveBeenCalledWith('u@e.com', 'pw');
      expect(user.access_token).toBe('tok');
      expect(window.localStorage.getItem(TOKEN_KEY)).toBe('tok');
      expect(window.localStorage.getItem(USER_KEY)).toContain('"name":"U"');
    });

    it('api 报错时透传错误且不写入 localStorage', async () => {
      (apiLogin as any).mockRejectedValueOnce(new Error('网络错误'));
      await expect(login('u@e.com', 'pw')).rejects.toThrow('网络错误');
      expect(window.localStorage.getItem(TOKEN_KEY)).toBeNull();
      expect(window.localStorage.getItem(USER_KEY)).toBeNull();
    });
  });

  describe('getToken / getCurrentUser / isLoggedIn', () => {
    it('无 token 时 getToken 返回 null、isLoggedIn 返回 false', () => {
      expect(getToken()).toBeNull();
      expect(isLoggedIn()).toBe(false);
      expect(getCurrentUser()).toBeNull();
    });

    it('写入 token 后可读取', () => {
      const u: AuthUser = {
        access_token: 'abc',
        role: 'doctor',
        name: '李四',
        email: 'l@e.com',
      };
      window.localStorage.setItem(TOKEN_KEY, u.access_token);
      window.localStorage.setItem(USER_KEY, JSON.stringify(u));
      expect(getToken()).toBe('abc');
      expect(isLoggedIn()).toBe(true);
      expect(getCurrentUser()).toEqual(u);
    });

    it('USER_KEY 为非法 JSON 时 getCurrentUser 返回 null', () => {
      window.localStorage.setItem(TOKEN_KEY, 'abc');
      window.localStorage.setItem(USER_KEY, '{not-json');
      expect(getCurrentUser()).toBeNull();
    });
  });

  describe('logout', () => {
    it('清除 localStorage 并跳转到 /', () => {
      window.localStorage.setItem(TOKEN_KEY, 'x');
      window.localStorage.setItem(USER_KEY, '{}');
      // mock location.href setter
      const hrefSetter = vi.fn();
      Object.defineProperty(window, 'location', {
        configurable: true,
        value: {
          get href() {
            return '/';
          },
          set href(v: string) {
            hrefSetter(v);
          },
          pathname: '/dashboard',
        },
      });
      logout();
      expect(window.localStorage.getItem(TOKEN_KEY)).toBeNull();
      expect(window.localStorage.getItem(USER_KEY)).toBeNull();
      expect(hrefSetter).toHaveBeenCalledWith('/');
    });
  });
});
