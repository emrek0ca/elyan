/**
 * JarvisPanel — Real-time Jarvis status panel.
 *
 * Shows: active agents, channel status, live activity, system health.
 * Data driven by runtime-store (populated via WebSocket events).
 */
import { useEffect, useRef, useState } from "react";
import {
  Activity, Bot, Cable, Cpu, Mic, MicOff, Sparkles, Zap,
} from "@/vendor/lucide-react";
import { Surface } from "@/components/primitives/Surface";
import { StatusBadge } from "@/components/primitives/StatusBadge";
import { useRuntimeStore } from "@/stores/runtime-store";
import type { JarvisAgentActivity } from "@/stores/runtime-store";
import { cn } from "@/utils/cn";

// ── VoiceButton ──────────────────────────────────────────────────────────────

function VoiceButton({ className }: { className?: string }) {
  const [listening, setListening] = useState(false);
  const [busy, setBusy] = useState(false);

  async function toggle() {
    if (busy) return;
    setBusy(true);
    try {
      const next = !listening;
      setListening(next);
      // Fire trigger to backend voice pipeline
      if (next) {
        await fetch("/api/jarvis/voice/trigger", { method: "POST" }).catch(() => null);
      }
    } finally {
      setBusy(false);
    }
  }

  return (
    <button
      onClick={() => void toggle()}
      disabled={busy}
      title={listening ? "Dinlemeyi durdur" : "Jarvis'e sesli komut ver"}
      className={cn(
        "flex h-10 w-10 items-center justify-center rounded-full border transition-all duration-200",
        listening
          ? "animate-pulse border-[var(--accent-primary)] bg-[color-mix(in_srgb,var(--accent-soft)_60%,transparent)] text-[var(--accent-primary)]"
          : "border-[var(--glass-border)] bg-[var(--glass-panel)] text-[var(--text-secondary)] hover:border-[var(--accent-primary)] hover:text-[var(--accent-primary)]",
        busy && "opacity-50 cursor-not-allowed",
        className,
      )}
    >
      {listening ? <Mic size={16} /> : <MicOff size={16} />}
    </button>
  );
}

// ── AgentActivityFeed ────────────────────────────────────────────────────────

function AgentActivityFeed({ items }: { items: JarvisAgentActivity[] }) {
  const endRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    endRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [items.length]);

  if (!items.length) {
    return (
      <div className="flex h-20 items-center justify-center text-[12px] text-[var(--text-tertiary)]">
        Henüz aktivite yok
      </div>
    );
  }

  return (
    <div className="max-h-[180px] space-y-1.5 overflow-y-auto">
      {items.map((item) => (
        <div
          key={item.id}
          className="flex items-center gap-2.5 rounded-[12px] bg-[var(--glass-elevated)] px-3 py-2"
        >
          <div
            className={cn(
              "h-1.5 w-1.5 shrink-0 rounded-full",
              item.status === "running" && "animate-pulse bg-[var(--accent-primary)]",
              item.status === "done" && "bg-emerald-500",
              item.status === "error" && "bg-red-500",
            )}
          />
          <span className="text-[11px] font-medium text-[var(--accent-primary)]">{item.agent}</span>
          <span className="flex-1 truncate text-[11px] text-[var(--text-secondary)]">{item.action}</span>
          <span className="shrink-0 text-[10px] text-[var(--text-tertiary)]">
            {new Date(item.ts).toLocaleTimeString("tr", { hour: "2-digit", minute: "2-digit", second: "2-digit" })}
          </span>
        </div>
      ))}
      <div ref={endRef} />
    </div>
  );
}

// ── ChannelStatusRow ─────────────────────────────────────────────────────────

interface ChannelInfo {
  key: keyof ReturnType<typeof useRuntimeStore.getState>["jarvisChannelStatus"];
  label: string;
}

const CHANNELS: ChannelInfo[] = [
  { key: "telegram", label: "Telegram" },
  { key: "whatsapp", label: "WhatsApp" },
  { key: "imessage", label: "iMessage" },
  { key: "desktop", label: "Desktop" },
];

function ChannelStatusRow() {
  const channelStatus = useRuntimeStore((s) => s.jarvisChannelStatus);

  return (
    <div className="flex flex-wrap gap-2">
      {CHANNELS.map((ch) => {
        const connected = channelStatus[ch.key];
        return (
          <div
            key={ch.key}
            className={cn(
              "flex items-center gap-1.5 rounded-[10px] border px-2.5 py-1 text-[11px] font-medium",
              connected
                ? "border-emerald-500/30 bg-emerald-500/10 text-emerald-600 dark:text-emerald-400"
                : "border-[var(--glass-border)] bg-[var(--glass-panel)] text-[var(--text-tertiary)]",
            )}
          >
            <div
              className={cn(
                "h-1.5 w-1.5 rounded-full",
                connected ? "bg-emerald-500" : "bg-[var(--text-tertiary)]",
              )}
            />
            {ch.label}
          </div>
        );
      })}
    </div>
  );
}

// ── SystemHealthBar ──────────────────────────────────────────────────────────

function SystemHealthBar() {
  const health = useRuntimeStore((s) => s.jarvisSystemHealth);

  return (
    <div className="flex flex-wrap items-center gap-3 text-[11px] text-[var(--text-secondary)]">
      <span className="flex items-center gap-1">
        <Cpu size={11} />
        {health.cpu.toFixed(0)}%
      </span>
      <span className="flex items-center gap-1">
        <Zap size={11} className={health.charging ? "text-emerald-500" : ""} />
        {health.batteryPct}% {health.charging ? "şarj" : ""}
      </span>
      {health.activeModel && (
        <span className="flex items-center gap-1">
          <Sparkles size={11} />
          {health.activeModel}
        </span>
      )}
    </div>
  );
}

// ── JarvisPanel (main) ───────────────────────────────────────────────────────

export function JarvisPanel() {
  const connectionState = useRuntimeStore((s) => s.connectionState);
  const activities = useRuntimeStore((s) => s.jarvisActivities);
  const setJarvisChannelStatus = useRuntimeStore((s) => s.setJarvisChannelStatus);

  // Sync desktop channel status with WebSocket connection state
  useEffect(() => {
    setJarvisChannelStatus({ desktop: connectionState === "connected" });
  }, [connectionState, setJarvisChannelStatus]);

  const isActive = connectionState === "connected";

  return (
    <Surface tone="card" className="space-y-4 p-5">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-2.5">
          <div
            className={cn(
              "flex h-8 w-8 items-center justify-center rounded-full border",
              isActive
                ? "border-[var(--accent-primary)] bg-[color-mix(in_srgb,var(--accent-soft)_50%,transparent)]"
                : "border-[var(--glass-border)] bg-[var(--glass-panel)]",
            )}
          >
            <Bot
              size={15}
              className={isActive ? "text-[var(--accent-primary)]" : "text-[var(--text-tertiary)]"}
            />
          </div>
          <div>
            <div className="text-[13px] font-semibold tracking-tight text-[var(--text-primary)]">
              Elyan Jarvis
            </div>
            <div className="text-[11px] text-[var(--text-tertiary)]">
              Çoklu ajan operatör
            </div>
          </div>
        </div>
        <div className="flex items-center gap-2">
          <VoiceButton />
          <StatusBadge tone={isActive ? "success" : "error"}>
            {isActive ? "aktif" : "beklemede"}
          </StatusBadge>
        </div>
      </div>

      {/* Channels */}
      <div>
        <div className="mb-2 flex items-center gap-1.5 text-[11px] font-medium uppercase tracking-wider text-[var(--text-tertiary)]">
          <Cable size={10} />
          Kanallar
        </div>
        <ChannelStatusRow />
      </div>

      {/* Live Activity */}
      <div>
        <div className="mb-2 flex items-center gap-1.5 text-[11px] font-medium uppercase tracking-wider text-[var(--text-tertiary)]">
          <Activity size={10} />
          Canlı Aktivite
        </div>
        <AgentActivityFeed items={activities} />
      </div>

      {/* System Health */}
      <div className="border-t border-[var(--glass-border)] pt-3">
        <SystemHealthBar />
      </div>
    </Surface>
  );
}
