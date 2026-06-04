import { afterEach, describe, expect, it, vi } from 'vitest';
import { createPreviewApi } from '../src/renderer/desktop-api';

describe('browser preview desktop api', () => {
  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it('routes auth requests through the local preview runtime bridge', async () => {
    const fetchMock = vi.fn(async () => {
      return new Response(
        JSON.stringify({
          id: 'req_login',
          taskId: 'task_login',
          ok: true,
          capability: 'backend.auth_login',
          result: { ok: true },
          events: [],
          artifacts: [],
          error: null,
          durationMs: 1,
          requestId: 'req_login',
        }),
        { status: 200, headers: { 'Content-Type': 'application/json' } },
      );
    });
    vi.stubGlobal('fetch', fetchMock);

    const api = createPreviewApi();
    const response = await api.request({
      id: 'req_login',
      taskId: 'task_login',
      capability: 'backend.auth_login',
      payload: {
        email: 'user@example.com',
        password: 'secret',
      },
    });

    expect(response.ok).toBe(true);
    expect(fetchMock).toHaveBeenCalledWith(
      '/__elyan_preview/request',
      expect.objectContaining({
        method: 'POST',
        body: expect.stringContaining('backend.auth_login'),
      }),
    );
  });
});
