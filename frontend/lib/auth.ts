import { login as apiLogin } from './api';

const TOKEN_KEY = 'ai_drug_token';
const USER_KEY = 'ai_drug_user';
const TOKEN_COOKIE = 'ai_drug_token';

export interface AuthUser {
  access_token: string;
  role: string;
  name: string;
  email: string;
}

const setCookie = (name: string, value: string, days: number = 7): void => {
  if (typeof window === 'undefined') return;
  const expires = new Date(Date.now() + days * 24 * 60 * 60 * 1000).toUTCString();
  document.cookie = `${name}=${encodeURIComponent(value)}; expires=${expires}; path=/; SameSite=Lax`;
};

const deleteCookie = (name: string): void => {
  if (typeof window === 'undefined') return;
  document.cookie = `${name}=; expires=Thu, 01 Jan 1970 00:00:00 GMT; path=/; SameSite=Lax`;
};

export const login = async (email: string, password: string): Promise<AuthUser> => {
  const data = await apiLogin(email, password);
  if (typeof window !== 'undefined') {
    localStorage.setItem(TOKEN_KEY, data.access_token);
    localStorage.setItem(USER_KEY, JSON.stringify(data));
    setCookie(TOKEN_COOKIE, data.access_token, 7);
  }
  return data;
};

export const logout = (): void => {
  if (typeof window !== 'undefined') {
    localStorage.removeItem(TOKEN_KEY);
    localStorage.removeItem(USER_KEY);
    deleteCookie(TOKEN_COOKIE);
    window.history.replaceState(null, '', '/');
    window.dispatchEvent(new PopStateEvent('popstate'));
  }
};

export const getToken = (): string | null => {
  if (typeof window === 'undefined') {
    return null;
  }
  return localStorage.getItem(TOKEN_KEY);
};

export const getCurrentUser = (): AuthUser | null => {
  if (typeof window === 'undefined') return null;
  const raw = localStorage.getItem(USER_KEY);
  if (!raw) return null;
  try {
    return JSON.parse(raw) as AuthUser;
  } catch {
    return null;
  }
};

export const isLoggedIn = (): boolean => {
  return !!getToken();
};
