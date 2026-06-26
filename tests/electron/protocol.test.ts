import { describe, expect, it } from 'vitest';
import { createRuntimeUnavailableResponse, ensureRuntimeRequest, isRuntimeResponse } from '../../src/shared/protocol';

describe('shared runtime protocol', () => {
  it('fills request and task ids without changing capability', () => {
    const request = ensureRuntimeRequest({ capability: 'runtime.status' });
    expect(request.capability).toBe('runtime.status');
    expect(request.id).toMatch(/^req_/);
    expect(request.taskId).toMatch(/^task_/);
    expect(request.payload).toEqual({});
  });

  it('creates safe unavailable envelope', () => {
    const response = createRuntimeUnavailableResponse({ id: 'req_1', taskId: 'task_1', capability: 'bootstrap' });
    expect(isRuntimeResponse(response)).toBe(true);
    expect(response.ok).toBe(false);
    expect(response.error?.code).toBe('RUNTIME_UNAVAILABLE');
    expect(response.result).toBeNull();
  });
});
