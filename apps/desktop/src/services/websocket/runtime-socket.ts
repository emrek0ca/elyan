import { useRuntimeStore } from "@/stores/runtime-store";
import type { JarvisAgentActivity } from "@/stores/runtime-store";

type RuntimeEventListener = (event: { type: string; payload: unknown }) => void;

// ── Jarvis event dispatchers ─────────────────────────────────────────────────

function dispatchJarvisEvent(type: string, payload: unknown): void {
  const store = useRuntimeStore.getState();
  const data = payload as Record<string, unknown>;

  switch (type) {
    case "agent.specialist.invoked": {
      const activity: JarvisAgentActivity = {
        id: String(data.task_id || data.child_task_id || crypto.randomUUID()),
        agent: String(data.specialist_key || data.agent || "Agent"),
        action: String(data.prompt_preview || data.action || "Çalışıyor…"),
        status: "running",
        ts: Date.now(),
      };
      store.pushJarvisActivity(activity);
      break;
    }
    case "agent.specialist.completed": {
      const id = String(data.task_id || data.child_task_id || "");
      if (id) {
        store.updateJarvisActivity(id, {
          status: data.success === false ? "error" : "done",
        });
      } else {
        // Fallback: push a completion event
        store.pushJarvisActivity({
          id: crypto.randomUUID(),
          agent: String(data.specialist_key || "Agent"),
          action: `Tamamlandı (${data.latency_ms ?? "?"}ms)`,
          status: data.success === false ? "error" : "done",
          ts: Date.now(),
        });
      }
      break;
    }
    case "computer.action.executed": {
      store.pushJarvisActivity({
        id: crypto.randomUUID(),
        agent: "MacOS",
        action: String(data.action || data.description || "Bilgisayar komutu"),
        status: data.success === false ? "error" : "done",
        ts: Date.now(),
      });
      break;
    }
    case "proactive.alert.fired": {
      store.pushJarvisActivity({
        id: crypto.randomUUID(),
        agent: "Monitor",
        action: String(data.message || data.alert || "Sistem uyarısı"),
        status: "running",
        ts: Date.now(),
      });
      break;
    }
    case "channel.message.received": {
      const channelType = String(data.channel_type || "").toLowerCase();
      if (channelType === "telegram") store.setJarvisChannelStatus({ telegram: true });
      else if (channelType === "whatsapp") store.setJarvisChannelStatus({ whatsapp: true });
      else if (channelType === "imessage") store.setJarvisChannelStatus({ imessage: true });
      store.pushJarvisActivity({
        id: crypto.randomUUID(),
        agent: channelType || "Channel",
        action: String(data.preview || data.text || "Yeni mesaj"),
        status: "done",
        ts: Date.now(),
      });
      break;
    }
    case "channel.connected": {
      const ch = String(data.channel_type || "").toLowerCase();
      if (ch === "telegram") store.setJarvisChannelStatus({ telegram: true });
      else if (ch === "whatsapp") store.setJarvisChannelStatus({ whatsapp: true });
      else if (ch === "imessage") store.setJarvisChannelStatus({ imessage: true });
      else if (ch === "desktop") store.setJarvisChannelStatus({ desktop: true });
      break;
    }
    case "channel.disconnected": {
      const ch = String(data.channel_type || "").toLowerCase();
      if (ch === "telegram") store.setJarvisChannelStatus({ telegram: false });
      else if (ch === "whatsapp") store.setJarvisChannelStatus({ whatsapp: false });
      else if (ch === "imessage") store.setJarvisChannelStatus({ imessage: false });
      else if (ch === "desktop") store.setJarvisChannelStatus({ desktop: false });
      break;
    }
    case "system.health.update": {
      store.setJarvisSystemHealth({
        cpu: typeof data.cpu === "number" ? data.cpu : undefined,
        batteryPct: typeof data.battery_pct === "number" ? data.battery_pct : undefined,
        charging: typeof data.charging === "boolean" ? data.charging : undefined,
        activeModel: typeof data.active_model === "string" ? data.active_model : undefined,
      });
      break;
    }
    default:
      break;
  }
}

// ── RuntimeSocketBridge ──────────────────────────────────────────────────────

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
          const eventType = parsed.type || parsed.event || "runtime_event";
          const eventPayload = parsed.data ?? parsed;

          // Dispatch Jarvis-specific events to store
          dispatchJarvisEvent(eventType, eventPayload);

          // Forward all events to caller
          onEvent({ type: eventType, payload: eventPayload });
        } catch {
          onEvent({ type: "runtime_event", payload: message.data });
        }
      };
      this.socket.onclose = () => {
        this.socket = null;
        useRuntimeStore.getState().setJarvisChannelStatus({ desktop: false });
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
