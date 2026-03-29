type RuntimeEventListener = (event: { type: string; payload: unknown }) => void;

export class RuntimeSocketBridge {
  private socket: WebSocket | null = null;

  isConnected() {
    return this.socket?.readyState === WebSocket.OPEN || this.socket?.readyState === WebSocket.CONNECTING;
  }

  connect(baseUrl: string, token: string, onEvent: RuntimeEventListener): () => void {
    try {
      const normalizedBaseUrl = baseUrl.trim().replace(/\/+$/, "");
      if (!token.trim()) {
        return () => undefined;
      }
      const socketUrl = new URL(`${normalizedBaseUrl}/ws/dashboard`);
      socketUrl.protocol = socketUrl.protocol === "https:" ? "wss:" : "ws:";
      socketUrl.searchParams.set("token", token.trim());

      this.socket?.close();
      this.socket = new WebSocket(socketUrl.toString());
      this.socket.onmessage = (message) => {
        try {
          const parsed = JSON.parse(String(message.data || "{}")) as {
            type?: string;
            event?: string;
            data?: unknown;
          };
          onEvent({
            type: parsed.type || parsed.event || "runtime_event",
            payload: parsed.data ?? parsed,
          });
        } catch {
          onEvent({ type: "runtime_event", payload: message.data });
        }
      };
      this.socket.onclose = () => {
        this.socket = null;
      };
      this.socket.onerror = () => {
        this.socket = null;
      };
    } catch {
      return () => undefined;
    }

    return () => {
      this.socket?.close();
      this.socket = null;
    };
  }
}

export const runtimeSocketBridge = new RuntimeSocketBridge();
