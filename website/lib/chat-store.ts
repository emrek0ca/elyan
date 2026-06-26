"use client";

import { useState, useCallback, useRef, useEffect } from 'react';
import { apiFetch, getAccessToken } from './api-client';
import { SSEManager } from './sse-manager';
import { ChatMessageBlock, parseMessageBlocksFromJson } from './chat-block-parser';

export type ChatMessage = {
  id: string;
  isUser: boolean;
  content: string;
  blocks: ChatMessageBlock[];
  status?: 'sending' | 'sent' | 'error';
  timestamp: string;
};

export type ChatSession = {
  id: string;
  title: string;
  createdAt: string;
};

type SendMessageOptions = {
  displayContent?: string;
  metadata?: Record<string, unknown>;
  requestedCapabilities?: string[];
};

export function buildChatMessagePayload(
  content: string,
  options: SendMessageOptions = {},
  activeSessionId: string | null = null
): Record<string, unknown> {
  return {
    content,
    ...(options.metadata && Object.keys(options.metadata).length > 0
      ? { metadata: options.metadata }
      : {}),
    ...(options.requestedCapabilities && options.requestedCapabilities.length > 0
      ? { requestedCapabilities: options.requestedCapabilities }
      : {}),
    ...(activeSessionId ? { sessionId: activeSessionId } : {})
  };
}

function mapAssistantPayload(payload: any): ChatMessage | null {
  const assistant = payload?.assistantMessage || payload?.message || payload;
  if (!assistant || typeof assistant !== 'object') return null;
  const blocks = parseMessageBlocksFromJson(assistant, [
    assistant.content,
    assistant.text,
    payload?.delta
  ]);
  if (blocks.length === 0) return null;

  return {
    id: assistant.id || payload?.messageId || payload?.aggregateId || Date.now().toString(),
    isUser: false,
    content: assistant.content || payload?.delta || '',
    blocks,
    timestamp: assistant.updatedAt || assistant.createdAt || new Date().toISOString(),
    status: assistant.status === 'failed' ? 'error' : 'sent'
  };
}

function upsertAssistantMessage(messages: ChatMessage[], nextMessage: ChatMessage): ChatMessage[] {
  const existingIndex = messages.findIndex((message) => message.id === nextMessage.id);
  if (existingIndex >= 0) {
    return messages.map((message, index) => index === existingIndex ? { ...message, ...nextMessage } : message);
  }

  const lastMessage = messages[messages.length - 1];
  if (lastMessage && !lastMessage.isUser && lastMessage.status !== 'error') {
    return [
      ...messages.slice(0, -1),
      nextMessage
    ];
  }

  return [...messages, nextMessage];
}

export function useChat() {
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [sessions, setSessions] = useState<ChatSession[]>([]);
  const [activeSessionId, setActiveSessionId] = useState<string | null>(null);
  const [isHistoryLoading, setIsHistoryLoading] = useState(false);
  const [isSending, setIsSending] = useState(false);
  const sseManagerRef = useRef<SSEManager | null>(null);

  // Initialize SSE — only connect when access token is available.
  // Auth init (refreshAccessToken) is async; we retry once after 500ms to
  // cover the window between component mount and token hydration.
  useEffect(() => {
    const sse = new SSEManager({
      onReady: (e) => {
        console.log('SSE realtime ready:', e);
      },
      onEvent: (e) => {
        if (['chat.message.delta', 'chat.message.created', 'chat.message.updated'].includes(e.topic)) {
          const assistantMessage = mapAssistantPayload(e.payload);
          if (assistantMessage) {
            setMessages(prev => upsertAssistantMessage(prev, assistantMessage));
          }
          return;
        }

        // Reconcile incoming backend blocks with local state.
        // Backend is truth: we update/append based on aggregateId.
        if (e.topic === 'message.appended' && e.payload?.blocks) {
          const assistantMessage = mapAssistantPayload({
            ...e.payload,
            aggregateId: e.aggregateId,
            messageId: e.aggregateId
          });
          if (assistantMessage) {
            setMessages(prev => upsertAssistantMessage(prev, assistantMessage));
          }
        }
      },
      onError: (e) => {
        // Expected transport interruptions are retried by SSEManager.
      }
    });

    sseManagerRef.current = sse;

    // Guard: only connect when a valid token is present.
    // Auth provider init is async, so we attempt immediately, then retry once.
    const tryConnect = () => {
      if (!sseManagerRef.current) return;
      if (getAccessToken()) {
        sseManagerRef.current.connect();
      } else {
        // Single retry after 500ms — covers async token hydration race
        setTimeout(() => {
          const token = getAccessToken();
          if (token && sseManagerRef.current) {
            sseManagerRef.current.connect();
          }
        }, 500);
      }
    };

    tryConnect();

    return () => {
      sse.disconnect();
      sseManagerRef.current = null;
    };
  }, []);

  const loadHistory = useCallback(async () => {
    setIsHistoryLoading(true);
    try {
      const data = await apiFetch('/v1/chat/sessions?limit=20');
      if (data.data) {
        setSessions(data.data);
      }
    } catch (e) {
      console.warn('Failed to load history', e);
    } finally {
      setIsHistoryLoading(false);
    }
  }, []);

  const loadSession = useCallback(async (sessionId: string) => {
    setActiveSessionId(sessionId);
    try {
      const data = await apiFetch(`/v1/chat/sessions/${sessionId}/messages`);
      if (data.data) {
        const mapped = data.data.map((m: any) => ({
          id: m.id,
          isUser: m.source === 'user',
          content: m.content || '',
          blocks: parseMessageBlocksFromJson(m),
          timestamp: m.createdAt,
          status: 'sent'
        }));
        setMessages(mapped.reverse());
      }
    } catch (e) {
      console.warn('Failed to load session messages', e);
    }
  }, []);

  const sendMessage = useCallback(async (content: string, options: SendMessageOptions = {}) => {
    if (!content.trim()) return;

    const tempId = Date.now().toString();
    const displayContent = options.displayContent?.trim() || content;
    const newMessage: ChatMessage = {
      id: tempId,
      isUser: true,
      content: displayContent,
      blocks: [{ type: 'text', markdown: displayContent, visibility: 'user_visible' }],
      status: 'sending',
      timestamp: new Date().toISOString()
    };

    setMessages(prev => [...prev, newMessage]);
    setIsSending(true);

    try {
      const payload = buildChatMessagePayload(content, options, activeSessionId);

      const res = await apiFetch('/v1/chat/messages', {
        method: 'POST',
        body: JSON.stringify(payload)
      });

      // Update to sent
      setMessages(prev => prev.map(m => m.id === tempId ? { ...m, status: 'sent', id: res.id || tempId } : m));
      
      if (!activeSessionId && res.sessionId) {
        setActiveSessionId(res.sessionId);
        // We should also refresh history to show this new session
        loadHistory();
      }

      // Optionally we can do authoritative refresh here if we don't rely fully on SSE
      // await loadSession(res.sessionId || activeSessionId);

    } catch (e) {
      console.warn('Send failed', e);
      setMessages(prev => prev.map(m => m.id === tempId ? { ...m, status: 'error' } : m));
    } finally {
      setIsSending(false);
    }
  }, [activeSessionId, loadHistory]);

  const clearChat = useCallback(() => {
    setActiveSessionId(null);
    setMessages([]);
  }, []);

  const approveTask = useCallback(async (taskId: string) => {
    try {
      await apiFetch(`/v1/tasks/${taskId}/approval`, {
        method: 'POST',
        body: JSON.stringify({ approved: true })
      });
      // SSE will handle the state update of the actionable block natively.
    } catch (e) {
      console.warn('Approval failed', e);
    }
  }, []);

  return {
    messages,
    sessions,
    activeSessionId,
    isHistoryLoading,
    isSending,
    loadHistory,
    loadSession,
    sendMessage,
    clearChat,
    approveTask
  };
}
