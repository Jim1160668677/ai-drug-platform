import { describe, it, expect, beforeEach } from 'vitest';
import { useAppStore } from './store';

describe('useAppStore', () => {
  beforeEach(() => {
    // 重置到初始状态
    useAppStore.setState({
      user: null,
      currentProject: null,
      sidebarCollapsed: false,
    });
    if (typeof window !== 'undefined') {
      window.localStorage.clear();
    }
  });

  it('初始状态正确', () => {
    const s = useAppStore.getState();
    expect(s.user).toBeNull();
    expect(s.currentProject).toBeNull();
    expect(s.sidebarCollapsed).toBe(false);
  });

  it('setUser 设置用户对象', () => {
    const user = { role: 'researcher', name: '张三', email: 'z@e.com' };
    useAppStore.getState().setUser(user);
    expect(useAppStore.getState().user).toEqual(user);
  });

  it('clearUser 清除用户', () => {
    useAppStore.getState().setUser({ role: 'researcher', name: '张三', email: 'z@e.com' });
    useAppStore.getState().clearUser();
    expect(useAppStore.getState().user).toBeNull();
  });

  it('setProject 设置当前项目', () => {
    const project = {
      id: 'p1',
      name: '肺癌项目',
      cancer_type: 'NSCLC',
      stage: 'discovery',
      status: 'active',
    };
    useAppStore.getState().setProject(project);
    expect(useAppStore.getState().currentProject).toEqual(project);
  });

  it('setProject(null) 清除当前项目', () => {
    useAppStore.getState().setProject({ id: 'p1', name: 'P' });
    useAppStore.getState().setProject(null);
    expect(useAppStore.getState().currentProject).toBeNull();
  });

  it('toggleSidebar 切换布尔值', () => {
    expect(useAppStore.getState().sidebarCollapsed).toBe(false);
    useAppStore.getState().toggleSidebar();
    expect(useAppStore.getState().sidebarCollapsed).toBe(true);
    useAppStore.getState().toggleSidebar();
    expect(useAppStore.getState().sidebarCollapsed).toBe(false);
  });

  it('多次 setUser 覆盖前值', () => {
    useAppStore.getState().setUser({ role: 'researcher', name: 'A', email: 'a@e.com' });
    useAppStore.getState().setUser({ role: 'doctor', name: 'B', email: 'b@e.com' });
    const u = useAppStore.getState().user;
    expect(u?.name).toBe('B');
    expect(u?.role).toBe('doctor');
  });
});
