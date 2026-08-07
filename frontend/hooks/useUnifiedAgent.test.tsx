import { describe, it, expect, vi, beforeEach } from 'vitest';
import { renderHook, act } from '@testing-library/react';
import { useUnifiedAgent } from './useUnifiedAgent';

vi.mock('@/lib/api', () => {
  return {
    api: {
      post: vi.fn(),
      get: vi.fn(),
    },
  };
});

import { api } from '@/lib/api';
const mockedApi = vi.mocked(api);

describe('useUnifiedAgent.sendMessage', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mockedApi.get.mockResolvedValue({ data: { items: [] } });
    localStorage.clear();
  });

  it('以 body 携带 message/capability_hint 调用 /intelligence/agent/chat', async () => {
    mockedApi.post.mockImplementation(async (url: string) => {
      if (url.includes('/intelligence/sessions')) {
        return { data: { id: 'session-1' } };
      }
      if (url.includes('/intelligence/agent/chat')) {
        return {
          data: {
            response: '答复',
            capability: 'qa',
            metadata: {},
          },
        };
      }
      return { data: {} };
    });

    const { result } = renderHook(() => useUnifiedAgent());

    await act(async () => {
      await result.current.sendMessage('测试问题', 'qa');
    });

    const call = mockedApi.post.mock.calls.find(([url]) =>
      String(url).includes('/intelligence/agent/chat'),
    );
    expect(call).toBeDefined();
    const [, body] = call as [string, any];
    expect(body).toMatchObject({ message: '测试问题', capability_hint: 'qa' });
    expect(body).not.toBeNull();
  });
});
