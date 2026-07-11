import { login as apiLogin } from './api';

const TOKEN_KEY = 'ai_drug_token';
const USER_KEY = 'ai_drug_user';

export interface AuthUser {
  access_token: string;
  role: string;
  name: string;
  email: string;
}

export const login = async (email: string, password: string): Promise<AuthUser> => {
  const data = await apiLogin(email, password);
  if (typeof window !== 'undefined') {
    localStorage.setItem(TOKEN_KEY, data.access_token);
    localStorage.setItem(USER_KEY, JSON.stringify(data));
  }
  return data;
};

export const logout = (): void => {
  if (typeof window !== 'undefined') {
    localStorage.removeItem(TOKEN_KEY);
    localStorage.removeItem(USER_KEY);
    window.location.href = '/';
  }
};

export const getToken = (): string | null => {
  if (typeof window === 'undefined') return null;
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
