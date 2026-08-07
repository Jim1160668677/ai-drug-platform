import { describe, it, expect, vi, beforeEach } from 'vitest';
import { renderHook, act } from '@testing-library/react';
import { useIntelligenceStream } from './useIntelligenceStream';

vi.mock('@/lib/api', () => {
  return {
    streamChat: vi.fn(),
  };
});

import { streamChat } from '@/lib/api';
const mockedStreamChat = vi.mocked(streamChat);

describe('useIntelligenceStream', () => {
  beforeEach(() => {
    mockedStreamChat.mockReset();
  });

  it('以正确参数调用 streamChat(message + projectId + forceMode)', async () => {
    const { result } = renderHook(() => useIntelligenceStream());
    await act(async () => {
      mockedStreamChat.mockImplementation(async (_sid: string, _msg: string, opts?: any) => {
        opts?.onChunk?.('部分');
        opts?.onDone?.('完整回复');
        return '完整回复';
      });
      await result.current.start('session-1', {
        message: '你好',
        project_id: 'proj-1',
        force_mode: 'chat',
      });
    });

    expect(mockedStreamChat).toHaveBeenCalledTimes(1);
    const [sessionId, message, opts] = mockedStreamChat.mock.calls[0] as any[];
    expect(sessionId).toBe('session-1');
    expect(message).toBe('你好');
    expect(opts?.projectId).toBe('proj-1');
    expect(opts?.forceMode).toBe('chat');
    expect(result.current.status).toBe('done');
    expect(result.current.streamingText).toBe('完整回复');
  });

  it('abort 后不触发 onDone', async () => {
    const onDone = vi.fn();
    const { result } = renderHook(() => useIntelligenceStream({ onDone }));
    let releaseChunk: (() => void) | undefined;
    await act(async () => {
      mockedStreamChat.mockImplementation(async (_sid: string, _msg: string, opts?: any) => {
        await new Promise<void>((resolve) => {
          releaseChunk = () => {
            opts?.onChunk?.('x');
            opts?.onDone?.('x');
            resolve();
          };
        });
        return 'x';
      });
      const startPromise = result.current.start('s1', { message: 'hi' });
      result.current.abort();
      releaseChunk?.();
      await startPromise;
    });
    expect(onDone).not.toHaveBeenCalled();
    expect(result.current.status).toBe('idle');
  });
});
