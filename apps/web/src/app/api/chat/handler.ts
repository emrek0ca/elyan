/**
 * Shared chat request handler for preview and main chat routes.
 * Layer: chat API support. Critical orchestration adapter, but it contains no route wiring itself.
 */
import { randomUUID } from 'crypto';
import { NextRequest } from 'next/server';
import { getControlPlaneSessionToken, isControlPlaneSessionConfigured } from '@/core/control-plane';
import { ControlPlaneAuthenticationError } from '@/core/control-plane/errors';
import { executeInteractionStream, normalizeInteractionError } from '@/core/interaction/orchestrator';
import { createApiErrorResponse } from '@/core/http/api-errors';
import { z } from 'zod';

type ChatLearningMode = 'disabled' | 'authenticated_optional';

type ChatHandlerOptions = {
  requireHostedSession: boolean;
  learningMode?: ChatLearningMode;
};

const chatMessageSchema = z.object({
  role: z.string().min(1),
  content: z.string().trim().min(1),
});

const chatRequestSchema = z.object({
  messages: z.array(chatMessageSchema).min(1),
  mode: z.enum(['speed', 'research']).optional(),
  modelId: z.string().trim().min(1).optional(),
  conversationId: z.string().trim().min(1).optional(),
});

function invalidChatRequest(code: string, message: string, issues?: Record<string, string[] | undefined>) {
  return createApiErrorResponse({
    status: 400,
    code,
    message,
    ...(issues ? { issues } : {}),
  });
}

async function readChatRequestBody(request: NextRequest) {
  const rawBody = await request.text();

  if (!rawBody.trim()) {
    return {
      ok: false as const,
      response: invalidChatRequest('empty_request_body', 'Chat request body is empty.'),
    };
  }

  try {
    return {
      ok: true as const,
      body: JSON.parse(rawBody) as unknown,
    };
  } catch {
    return {
      ok: false as const,
      response: invalidChatRequest('invalid_json_body', 'Chat request body must be valid JSON.'),
    };
  }
}

export async function handleChatRequest(request: NextRequest, options: ChatHandlerOptions) {
  try {
    const bodyResult = await readChatRequestBody(request);
    if (!bodyResult.ok) {
      return bodyResult.response;
    }

    const parsed = chatRequestSchema.safeParse(bodyResult.body);

    if (!parsed.success) {
      return invalidChatRequest(
        'invalid_chat_request',
        'Chat request body does not match the expected schema.',
        parsed.error.flatten().fieldErrors
      );
    }

    const { messages, mode, modelId, conversationId } = parsed.data;
    const latestUserMessage =
      [...messages].reverse().find((message) => message.role === 'user')?.content ?? messages[messages.length - 1].content;
    const requestId = request.headers.get('x-request-id')?.trim() || randomUUID();
    console.debug('[chat] request parsed', {
      requestId,
      surface: options.requireHostedSession ? 'main' : 'preview',
      messageCount: messages.length,
      mode: mode ?? 'default',
      hasModelId: !!modelId,
      hasConversationId: !!conversationId,
    });
    const shouldHydrateSession =
      isControlPlaneSessionConfigured() &&
      (options.requireHostedSession || options.learningMode === 'authenticated_optional');
    let controlPlaneSession = shouldHydrateSession ? await getControlPlaneSessionToken(request) : null;

    if (!controlPlaneSession?.accountId && options.learningMode === 'authenticated_optional') {
      controlPlaneSession = null;
    }

    if (options.requireHostedSession && isControlPlaneSessionConfigured() && !controlPlaneSession?.accountId) {
      throw new ControlPlaneAuthenticationError('Control-plane session is required for the main chat surface');
    }

    console.debug('[chat] dispatching interaction stream', {
      requestId,
      surface: options.requireHostedSession ? 'main' : 'preview',
      hostedSession: !!controlPlaneSession?.accountId,
    });

    return executeInteractionStream({
      source: 'web',
      text: latestUserMessage,
      mode,
      modelId,
      conversationId,
      requestId,
      controlPlaneSession,
      requireHostedSession: options.requireHostedSession,
      metadata: {
        learningMode: controlPlaneSession?.accountId ? 'authenticated' : 'anonymous_disabled',
      },
    });
  } catch (error: unknown) {
    console.error('[chat] endpoint error', error);
    const normalized = normalizeInteractionError(error);
    return createApiErrorResponse({
      status: normalized.status,
      code: normalized.code,
      message: normalized.message,
    });
  }
}
