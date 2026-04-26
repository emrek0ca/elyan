import { NextRequest } from 'next/server';
import { afterEach, describe, expect, it, vi } from 'vitest';

const mockSession = {
  sub: 'usr_1',
  email: 'ayla@example.com',
  name: 'Ayla',
  accountId: 'acct_1',
  ownerType: 'individual',
  role: 'owner',
  planId: 'cloud_assisted',
};

const mockService = {
  getInteractionContext: vi.fn(),
  promoteLearningDraft: vi.fn(),
  rotateDeviceToken: vi.fn(),
};

vi.mock('@/core/control-plane', () => ({
  getControlPlaneService: vi.fn(() => mockService),
}));

vi.mock('@/core/control-plane/session', () => ({
  requireControlPlaneSession: vi.fn(async () => mockSession),
  assertControlPlaneAccountAccess: vi.fn(),
}));

afterEach(() => {
  vi.clearAllMocks();
});

describe('control-plane interaction and device routes', () => {
  it('returns hosted interaction context blocks', async () => {
    mockService.getInteractionContext.mockResolvedValue({
      threadId: 'web:thread-1',
      contextBlocks: ['Pinned memory:\n- concise answers: prefer short replies'],
      thread: {
        threadId: 'web:thread-1',
        accountId: 'acct_1',
        source: 'web',
        title: 'Thread',
        summary: 'Summary',
        intent: 'research',
        status: 'active',
        messageCount: 2,
        createdAt: '2026-04-23T10:00:00.000Z',
        updatedAt: '2026-04-23T10:00:00.000Z',
        metadata: {},
      },
      memoryItems: [],
    });

    const { GET } = await import('@/app/api/control-plane/interactions/context/route');
    const request = new NextRequest(
      'http://127.0.0.1:3000/api/control-plane/interactions/context?query=short%20answers&source=web&conversationId=thread-1',
      { method: 'GET' }
    );

    const response = await GET(request);
    const payload = await response.json();

    expect(response.status).toBe(200);
    expect(payload.ok).toBe(true);
    expect(payload.context.threadId).toBe('web:thread-1');
    expect(mockService.getInteractionContext).toHaveBeenCalledWith('acct_1', {
      query: 'short answers',
      source: 'web',
      conversationId: 'thread-1',
      threadId: undefined,
    });
  });

  it('promotes learning drafts into long-lived memory for the bound account', async () => {
    mockService.promoteLearningDraft.mockResolvedValue({
      draft: {
        draftId: 'ldr_1',
        status: 'promoted',
      },
      memoryItem: {
        memoryId: 'mem_1',
        promoted: true,
      },
    });

    const { POST } = await import('@/app/api/control-plane/interactions/drafts/[draftId]/promote/route');
    const request = new NextRequest('http://127.0.0.1:3000/api/control-plane/interactions/drafts/ldr_1/promote', {
      method: 'POST',
    });

    const response = await POST(request, {
      params: Promise.resolve({ draftId: 'ldr_1' }),
    });
    const payload = await response.json();

    expect(response.status).toBe(200);
    expect(payload.ok).toBe(true);
    expect(payload.draft.status).toBe('promoted');
    expect(mockService.promoteLearningDraft).toHaveBeenCalledWith('acct_1', 'ldr_1');
  });

  it('rotates active device tokens and returns the new token binding', async () => {
    mockService.rotateDeviceToken.mockResolvedValue({
      ok: true,
      device: {
        deviceId: 'dev_1',
        deviceToken: 'devtok_rotated',
        status: 'active',
      },
      previousDeviceToken: 'devtok_original',
      rotatedAt: '2026-04-23T10:00:00.000Z',
    });

    const { POST } = await import('@/app/api/control-plane/devices/rotate/route');
    const request = new NextRequest('http://127.0.0.1:3000/api/control-plane/devices/rotate', {
      method: 'POST',
      headers: {
        authorization: 'Bearer devtok_original',
      },
    });

    const response = await POST(request);
    const payload = await response.json();

    expect(response.status).toBe(200);
    expect(payload.ok).toBe(true);
    expect(payload.previousDeviceToken).toBe('devtok_original');
    expect(mockService.rotateDeviceToken).toHaveBeenCalledWith('devtok_original');
  });
});
