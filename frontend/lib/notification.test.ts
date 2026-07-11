import { describe, it, expect, beforeEach, vi, afterEach } from 'vitest';
import { useNotificationStore, toast, NotificationType } from './notification';

describe('useNotificationStore', () => {
  beforeEach(() => {
    // 每个测试前清空通知
    useNotificationStore.getState().clearAll();
    vi.useFakeTimers();
  });

  afterEach(() => {
    vi.useRealTimers();
  });

  it('初始状态无通知', () => {
    expect(useNotificationStore.getState().notifications).toEqual([]);
  });

  it('showNotification 添加通知并返回 id', () => {
    const id = useNotificationStore.getState().showNotification({
      type: 'success',
      message: '操作成功',
    });
    expect(id).toBeTruthy();
    expect(typeof id).toBe('string');
    const list = useNotificationStore.getState().notifications;
    expect(list).toHaveLength(1);
    expect(list[0].message).toBe('操作成功');
    expect(list[0].type).toBe('success');
    expect(list[0].duration).toBe(4000); // 默认 4000ms
  });

  it('showNotification 透传 detail 与 duration', () => {
    useNotificationStore.getState().showNotification({
      type: 'error',
      message: '失败',
      detail: '原因详情',
      duration: 6000,
    });
    const n = useNotificationStore.getState().notifications[0];
    expect(n.detail).toBe('原因详情');
    expect(n.duration).toBe(6000);
  });

  it('duration > 0 时到期后自动移除', () => {
    useNotificationStore.getState().showNotification({
      type: 'info',
      message: '会消失',
      duration: 1000,
    });
    expect(useNotificationStore.getState().notifications).toHaveLength(1);
    vi.advanceTimersByTime(1000);
    expect(useNotificationStore.getState().notifications).toHaveLength(0);
  });

  it('duration = 0 时不自动移除', () => {
    useNotificationStore.getState().showNotification({
      type: 'warning',
      message: '常驻',
      duration: 0,
    });
    vi.advanceTimersByTime(100000);
    expect(useNotificationStore.getState().notifications).toHaveLength(1);
  });

  it('dismissNotification 移除指定 id', () => {
    const id1 = useNotificationStore.getState().showNotification({
      type: 'info',
      message: 'A',
      duration: 0,
    });
    const id2 = useNotificationStore.getState().showNotification({
      type: 'info',
      message: 'B',
      duration: 0,
    });
    useNotificationStore.getState().dismissNotification(id1);
    const list = useNotificationStore.getState().notifications;
    expect(list).toHaveLength(1);
    expect(list[0].id).toBe(id2);
  });

  it('clearAll 清空全部', () => {
    useNotificationStore.getState().showNotification({ type: 'info', message: 'A', duration: 0 });
    useNotificationStore.getState().showNotification({ type: 'info', message: 'B', duration: 0 });
    useNotificationStore.getState().clearAll();
    expect(useNotificationStore.getState().notifications).toEqual([]);
  });

  it('多个通知 id 唯一', () => {
    const ids = new Set<string>();
    for (let i = 0; i < 5; i++) {
      ids.add(
        useNotificationStore.getState().showNotification({
          type: 'info',
          message: `n${i}`,
          duration: 0,
        })
      );
    }
    expect(ids.size).toBe(5);
  });
});

describe('toast 便捷方法', () => {
  beforeEach(() => {
    useNotificationStore.getState().clearAll();
    vi.useFakeTimers();
  });

  afterEach(() => {
    vi.useRealTimers();
  });

  it('toast.success 添加 success 类型通知', () => {
    toast.success('保存成功');
    const n = useNotificationStore.getState().notifications[0];
    expect(n.type).toBe('success');
    expect(n.message).toBe('保存成功');
  });

  it('toast.success 透传 detail', () => {
    toast.success('保存成功', '已写入数据库');
    expect(useNotificationStore.getState().notifications[0].detail).toBe('已写入数据库');
  });

  it('toast.error 使用 6000ms 持续时间', () => {
    toast.error('保存失败');
    expect(useNotificationStore.getState().notifications[0].duration).toBe(6000);
  });

  it('toast.warning 添加 warning 类型通知', () => {
    toast.warning('请检查输入');
    expect(useNotificationStore.getState().notifications[0].type).toBe('warning');
  });

  it('toast.info 添加 info 类型通知', () => {
    toast.info('提示');
    expect(useNotificationStore.getState().notifications[0].type).toBe('info');
  });

  it('覆盖全部 NotificationType 类型', () => {
    const types: NotificationType[] = ['success', 'error', 'warning', 'info'];
    for (const t of types) {
      toast[t](`msg-${t}`);
    }
    const list = useNotificationStore.getState().notifications;
    expect(list.map((n) => n.type)).toEqual(types);
  });
});
