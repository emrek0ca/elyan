import { getAccessToken, getApiBaseUrl, refreshAccessToken } from './api-client';

export type SSEEvent = {
  eventId: string;
  seq: number;
  cursor: string;
  aggregateId: string;
  type: string;
  topic: string;
  userId: string;
  deviceId?: string;
  taskId?: string;
  payload: any;
};

export type RealtimeReadyEvent = {
  replaySupported: boolean;
  realtimeReady: boolean;
  resumeCursorTtlSeconds: number;
  sessionHydrationMode: string;
  degradedReason?: string;
  timestamp: string;
};

type SSEOptions = {
  onEvent: (event: SSEEvent) => void;
  onReady: (event: RealtimeReadyEvent) => void;
  onError?: (error: Error) => void;
  onClose?: () => void;
};

type ParsedSseMessage = {
  event: string;
  data: string;
  id?: string;
};

export function buildRealtimeStreamUrl({
  apiBase,
  origin,
  cursor,
  deviceId,
  taskId
}: {
  apiBase: string;
  origin: string;
  cursor?: string | null;
  deviceId?: string;
  taskId?: string;
}) {
  const normalizedApiBase = apiBase.endsWith('/') ? apiBase.slice(0, -1) : apiBase;
  const url = new URL(`${normalizedApiBase}/v1/realtime/stream`, origin);

  if (cursor) {
    url.searchParams.append('cursor', cursor);
  }
  if (deviceId) {
    url.searchParams.append('deviceId', deviceId);
  }
  if (taskId) {
    url.searchParams.append('taskId', taskId);
  }

  return url.toString();
}

export function parseSseMessage(rawMessage: string): ParsedSseMessage | null {
  const lines = rawMessage.replace(/\r\n/g, '\n').split('\n');
  let event = 'message';
  let id: string | undefined;
  const data: string[] = [];

  for (const line of lines) {
    if (!line || line.startsWith(':')) continue;
    const separator = line.indexOf(':');
    const field = separator >= 0 ? line.slice(0, separator) : line;
    const value = separator >= 0 ? line.slice(separator + 1).replace(/^ /, '') : '';

    if (field === 'event') event = value || 'message';
    if (field === 'id') id = value;
    if (field === 'data') data.push(value);
  }

  if (data.length === 0) return null;
  return { event, data: data.join('\n'), ...(id ? { id } : {}) };
}

export class SSEManager {
  private abortController: AbortController | null = null;
  private reconnectTimer: ReturnType<typeof setTimeout> | null = null;
  private currentCursor: string | null = null;
  private reconnectAttempts = 0;
  private readonly maxReconnectAttempts = 5;
  private readonly baseBackoffMs = 1000;
  private isConnected = false;
  private isConnecting = false;
  private isDestroyed = false;

  constructor(private readonly options: SSEOptions) {}

  public connect(deviceId?: string, taskId?: string) {
    if (this.isDestroyed || this.isConnected || this.isConnecting) return;
    void this.openStream(deviceId, taskId);
  }

  private async openStream(deviceId?: string, taskId?: string) {
    const token = getAccessToken();
    if (!token) return;

    this.isConnecting = true;
    const controller = new AbortController();
    this.abortController = controller;

    try {
      const origin = typeof window !== 'undefined' ? window.location.origin : 'https://elyan.dev';
      const url = buildRealtimeStreamUrl({
        apiBase: getApiBaseUrl(),
        origin,
        cursor: this.currentCursor,
        deviceId,
        taskId
      });
      const response = await fetch(url, {
        method: 'GET',
        mode: url.startsWith(origin) ? 'same-origin' : 'cors',
        credentials: 'include',
        headers: {
          Accept: 'text/event-stream',
          Authorization: `Bearer ${token}`,
          ...(this.currentCursor ? { 'Last-Event-ID': this.currentCursor } : {})
        },
        cache: 'no-store',
        signal: controller.signal
      });

      if (response.status === 401) {
        const refreshedToken = await refreshAccessToken();
        if (refreshedToken && !this.isDestroyed) {
          this.isConnecting = false;
          this.connect(deviceId, taskId);
        }
        return;
      }

      if (!response.ok) {
        throw new Error(`Realtime stream failed with status ${response.status}`);
      }
      if (!response.body) {
        throw new Error('Realtime stream body is unavailable');
      }

      this.isConnected = true;
      this.isConnecting = false;
      this.reconnectAttempts = 0;
      await this.consumeStream(response.body);

      if (!this.isDestroyed) {
        throw new Error('Realtime stream closed');
      }
    } catch (error) {
      if (this.isDestroyed || isAbortError(error)) return;
      this.options.onError?.(toError(error));
      this.scheduleReconnect(deviceId, taskId);
    } finally {
      if (this.abortController === controller) {
        this.abortController = null;
      }
      this.isConnected = false;
      this.isConnecting = false;
    }
  }

  private async consumeStream(stream: ReadableStream<Uint8Array>) {
    const reader = stream.getReader();
    const decoder = new TextDecoder();
    let buffer = '';

    while (!this.isDestroyed) {
      const { done, value } = await reader.read();
      if (done) break;
      buffer += decoder.decode(value, { stream: true }).replace(/\r\n/g, '\n');

      let boundary = buffer.indexOf('\n\n');
      while (boundary >= 0) {
        const rawMessage = buffer.slice(0, boundary);
        buffer = buffer.slice(boundary + 2);
        this.handleMessage(parseSseMessage(rawMessage));
        boundary = buffer.indexOf('\n\n');
      }
    }
  }

  private handleMessage(message: ParsedSseMessage | null) {
    if (!message) return;

    let payload: any;
    try {
      payload = JSON.parse(message.data);
    } catch {
      return;
    }

    if (message.id) this.currentCursor = message.id;
    if (typeof payload?.cursor === 'string' && payload.cursor) {
      this.currentCursor = payload.cursor;
    }

    if (message.event === 'ready') {
      this.options.onReady(payload as RealtimeReadyEvent);
      return;
    }
    if (message.event === 'ping') return;

    this.options.onEvent(payload as SSEEvent);
  }

  private scheduleReconnect(deviceId?: string, taskId?: string) {
    if (this.isDestroyed || this.reconnectTimer) return;
    if (this.reconnectAttempts >= this.maxReconnectAttempts) {
      this.options.onClose?.();
      return;
    }

    this.reconnectAttempts += 1;
    const jitter = Math.random() * 500;
    const delay = Math.pow(2, this.reconnectAttempts - 1) * this.baseBackoffMs + jitter;
    this.reconnectTimer = setTimeout(() => {
      this.reconnectTimer = null;
      this.connect(deviceId, taskId);
    }, delay);
  }

  public disconnect() {
    if (this.isDestroyed) return;
    this.isDestroyed = true;
    this.isConnected = false;
    this.isConnecting = false;
    this.abortController?.abort();
    this.abortController = null;
    if (this.reconnectTimer) {
      clearTimeout(this.reconnectTimer);
      this.reconnectTimer = null;
    }
    this.options.onClose?.();
  }
}

function isAbortError(error: unknown): boolean {
  return error instanceof Error && error.name === 'AbortError';
}

function toError(error: unknown): Error {
  return error instanceof Error ? error : new Error('Realtime connection interrupted');
}
