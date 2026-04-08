/**
 * ChatView — Elyan ile gerçek zamanlı sohbet ve komut arayüzü
 *
 * Streaming SSE: Ollama yanıtları token token görünür.
 * Komutlar (Safari aç, ekran görüntüsü al) anlık yanıt verir.
 * Onay gerektiren işlemler (restart, shutdown) burada sorulur.
 */
import { useCallback, useEffect, useRef, useState, KeyboardEvent } from "react";
import { Bot, Mic, MicOff, Send, User, X, AlertTriangle, Check } from "@/vendor/lucide-react";
import { Surface } from "@/components/primitives/Surface";
import { cn } from "@/utils/cn";

// ── Types ─────────────────────────────────────────────────────────────────────

type MessageRole = "user" | "assistant" | "system";

interface Message {
  id: string;
  role: MessageRole;
  text: string;
  streaming?: boolean;
  requiresApproval?: boolean;
  ts: number;
}

// ── Constants ──────────────────────────────────────────────────────────────────

const API_BASE = "";  // same origin

// ── Helpers ────────────────────────────────────────────────────────────────────

function genId() {
  return `${Date.now()}-${Math.random().toString(36).slice(2, 7)}`;
}

function isApprovalRequest(text: string): boolean {
  return text.includes("Onay Gerekiyor") || text.includes("geri alınamaz");
}

// ── Message Bubble ─────────────────────────────────────────────────────────────

function Bubble({ msg }: { msg: Message }) {
  const isUser = msg.role === "user";
  const isSystem = msg.role === "system";

  if (isSystem) {
    return (
      <div className="flex justify-center py-1">
        <span className="rounded-full bg-[var(--glass-elevated)] px-3 py-1 text-[11px] text-[var(--text-tertiary)]">
          {msg.text}
        </span>
      </div>
    );
  }

  return (
    <div className={cn("flex gap-2.5 py-1", isUser && "flex-row-reverse")}>
      {/* Avatar */}
      <div className={cn(
        "flex h-7 w-7 shrink-0 items-center justify-center rounded-full text-[var(--text-inverse)]",
        isUser
          ? "bg-[var(--accent-primary)]"
          : "bg-[color-mix(in_srgb,var(--accent-secondary)_40%,var(--glass-elevated))]",
      )}>
        {isUser ? <User size={13} /> : <Bot size={13} />}
      </div>

      {/* Bubble */}
      <div className={cn(
        "max-w-[82%] rounded-[16px] px-4 py-2.5",
        isUser
          ? "bg-[var(--accent-primary)] text-[var(--text-inverse)]"
          : msg.requiresApproval
            ? "border border-amber-400/40 bg-[color-mix(in_srgb,var(--color-warning-soft)_30%,var(--glass-elevated))]"
            : "bg-[var(--glass-elevated)]",
      )}>
        {msg.requiresApproval && (
          <div className="mb-2 flex items-center gap-1.5 text-amber-400">
            <AlertTriangle size={12} />
            <span className="text-[11px] font-semibold uppercase tracking-wide">Onay Gerekiyor</span>
          </div>
        )}
        <p className={cn(
          "whitespace-pre-wrap break-words text-[13px] leading-relaxed",
          isUser ? "text-[var(--text-inverse)]" : "text-[var(--text-primary)]",
        )}>
          {msg.text}
          {msg.streaming && (
            <span className="ml-0.5 inline-block h-3.5 w-0.5 animate-pulse rounded-full bg-current align-middle opacity-70" />
          )}
        </p>
        <div className={cn(
          "mt-1 text-right text-[10px]",
          isUser ? "text-[color-mix(in_srgb,var(--text-inverse)_60%,transparent)]" : "text-[var(--text-tertiary)]",
        )}>
          {new Date(msg.ts).toLocaleTimeString("tr", { hour: "2-digit", minute: "2-digit" })}
        </div>
      </div>
    </div>
  );
}

// ── Quick Actions ──────────────────────────────────────────────────────────────

const QUICK_ACTIONS = [
  "Sistem durumu nedir?",
  "Ekran görüntüsü al",
  "Bugünkü etkinliklerim",
  "CPU kullanımı nedir?",
];

// ── Main Component ─────────────────────────────────────────────────────────────

export function ChatView({ className }: { className?: string }) {
  const [messages, setMessages] = useState<Message[]>([
    {
      id: genId(),
      role: "system",
      text: "Elyan hazır — komut ver veya soru sor",
      ts: Date.now(),
    },
  ]);
  const [input, setInput] = useState("");
  const [streaming, setStreaming] = useState(false);
  const [voiceActive, setVoiceActive] = useState(false);
  const bottomRef = useRef<HTMLDivElement>(null);
  const inputRef = useRef<HTMLTextAreaElement>(null);
  const abortRef = useRef<AbortController | null>(null);

  // Auto-scroll on new message
  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages]);

  // ── Send message ────────────────────────────────────────────────────────────

  const send = useCallback(async (text: string) => {
    const trimmed = text.trim();
    if (!trimmed || streaming) return;

    setInput("");
    const userMsg: Message = { id: genId(), role: "user", text: trimmed, ts: Date.now() };
    setMessages(prev => [...prev, userMsg]);

    const assistantId = genId();
    const assistantMsg: Message = {
      id: assistantId, role: "assistant", text: "", streaming: true, ts: Date.now(),
    };
    setMessages(prev => [...prev, assistantMsg]);
    setStreaming(true);

    let accumulated = "";
    const controller = new AbortController();
    abortRef.current = controller;

    try {
      const resp = await fetch(`${API_BASE}/api/jarvis/chat/stream`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ text: trimmed, user_id: "desktop" }),
        signal: controller.signal,
      });

      if (!resp.ok) {
        throw new Error(`HTTP ${resp.status}`);
      }

      const reader = resp.body!.getReader();
      const decoder = new TextDecoder();

      while (true) {
        const { done, value } = await reader.read();
        if (done) break;

        const raw = decoder.decode(value, { stream: true });
        for (const line of raw.split("\n")) {
          if (!line.startsWith("data: ")) continue;
          const data = line.slice(6).trim();
          if (data === "[DONE]") break;
          try {
            const obj = JSON.parse(data) as { chunk: string };
            accumulated += obj.chunk;
            const isApproval = isApprovalRequest(accumulated);
            setMessages(prev =>
              prev.map(m =>
                m.id === assistantId
                  ? { ...m, text: accumulated, streaming: true, requiresApproval: isApproval }
                  : m,
              ),
            );
          } catch { /* skip malformed */ }
        }
      }
    } catch (err: unknown) {
      if (err instanceof Error && err.name === "AbortError") {
        accumulated = accumulated || "(iptal edildi)";
      } else {
        accumulated = accumulated || `Bağlantı hatası. Sunucunun çalıştığından emin ol.`;
      }
    } finally {
      const isApproval = isApprovalRequest(accumulated);
      setMessages(prev =>
        prev.map(m =>
          m.id === assistantId
            ? { ...m, text: accumulated || "…", streaming: false, requiresApproval: isApproval }
            : m,
        ),
      );
      setStreaming(false);
      abortRef.current = null;
      setTimeout(() => inputRef.current?.focus(), 50);
    }
  }, [streaming]);

  // ── Approval buttons ────────────────────────────────────────────────────────

  const sendApproval = useCallback((word: string) => {
    void send(word);
  }, [send]);

  // ── Voice toggle ─────────────────────────────────────────────────────────────

  const toggleVoice = useCallback(async () => {
    try {
      await fetch(`${API_BASE}/api/jarvis/voice/trigger`, { method: "POST" });
      setVoiceActive(v => !v);
    } catch { /* ignore */ }
  }, []);

  // ── Stop streaming ────────────────────────────────────────────────────────────

  const stopStream = useCallback(() => {
    abortRef.current?.abort();
  }, []);

  // ── Keyboard ─────────────────────────────────────────────────────────────────

  const onKeyDown = useCallback((e: KeyboardEvent<HTMLTextAreaElement>) => {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      void send(input);
    }
  }, [input, send]);

  // ── Last message needing approval ─────────────────────────────────────────────

  const lastMsg = messages[messages.length - 1];
  const awaitingApproval = lastMsg?.role === "assistant" && lastMsg.requiresApproval && !lastMsg.streaming;

  // ── Render ────────────────────────────────────────────────────────────────────

  return (
    <Surface tone="card" className={cn("flex flex-col", className)} style={{ minHeight: 0 }}>
      {/* Header */}
      <div className="flex items-center justify-between border-b border-[var(--glass-border)] px-4 py-3">
        <div className="flex items-center gap-2">
          <Bot size={15} className="text-[var(--accent-primary)]" />
          <span className="text-[13px] font-semibold text-[var(--text-primary)]">Elyan</span>
          {streaming && (
            <span className="rounded-full bg-[var(--accent-soft)] px-2 py-0.5 text-[10px] font-medium text-[var(--accent-primary)] animate-pulse">
              yazıyor…
            </span>
          )}
        </div>
        <div className="flex items-center gap-1.5">
          {streaming && (
            <button
              onClick={stopStream}
              className="flex items-center gap-1 rounded-full border border-[var(--glass-border)] px-2 py-1 text-[11px] text-[var(--text-secondary)] hover:text-red-400"
            >
              <X size={11} /> Durdur
            </button>
          )}
          <button
            onClick={() => void toggleVoice()}
            title={voiceActive ? "Sesi kapat" : "Sesli komut"}
            className={cn(
              "flex h-7 w-7 items-center justify-center rounded-full border transition-colors",
              voiceActive
                ? "animate-pulse border-[var(--accent-primary)] text-[var(--accent-primary)]"
                : "border-[var(--glass-border)] text-[var(--text-tertiary)] hover:text-[var(--accent-primary)]",
            )}
          >
            {voiceActive ? <Mic size={13} /> : <MicOff size={13} />}
          </button>
        </div>
      </div>

      {/* Messages */}
      <div className="flex-1 overflow-y-auto px-4 py-3 space-y-1.5" style={{ maxHeight: "380px" }}>
        {messages.map(msg => <Bubble key={msg.id} msg={msg} />)}
        <div ref={bottomRef} />
      </div>

      {/* Approval buttons */}
      {awaitingApproval && (
        <div className="flex justify-center gap-3 border-t border-[var(--glass-border)] px-4 py-3">
          <button
            onClick={() => sendApproval("evet")}
            className="flex items-center gap-1.5 rounded-full bg-amber-500 px-5 py-2 text-[13px] font-medium text-white hover:bg-amber-600"
          >
            <Check size={14} /> Evet, devam et
          </button>
          <button
            onClick={() => sendApproval("hayır")}
            className="flex items-center gap-1.5 rounded-full border border-[var(--glass-border)] px-5 py-2 text-[13px] text-[var(--text-secondary)] hover:text-[var(--text-primary)]"
          >
            <X size={14} /> İptal
          </button>
        </div>
      )}

      {/* Quick actions */}
      {messages.length <= 1 && !streaming && (
        <div className="flex flex-wrap gap-2 border-t border-[var(--glass-border)] px-4 py-2.5">
          {QUICK_ACTIONS.map(action => (
            <button
              key={action}
              onClick={() => void send(action)}
              className="rounded-full border border-[var(--glass-border)] px-3 py-1 text-[11px] text-[var(--text-secondary)] hover:border-[var(--accent-primary)] hover:text-[var(--accent-primary)] transition-colors"
            >
              {action}
            </button>
          ))}
        </div>
      )}

      {/* Input */}
      <div className="border-t border-[var(--glass-border)] px-3 py-3">
        <div className="flex items-end gap-2">
          <textarea
            ref={inputRef}
            value={input}
            onChange={e => setInput(e.target.value)}
            onKeyDown={onKeyDown}
            placeholder="Komut ver veya sor… (Enter gönderer, Shift+Enter yeni satır)"
            rows={1}
            disabled={streaming}
            className={cn(
              "flex-1 resize-none rounded-[14px] border border-[var(--glass-border)]",
              "bg-[var(--glass-elevated)] px-3.5 py-2.5 text-[13px] text-[var(--text-primary)]",
              "placeholder:text-[var(--text-tertiary)] focus:border-[var(--accent-primary)] focus:outline-none",
              "disabled:opacity-50 transition-colors",
            )}
            style={{ maxHeight: "120px", overflowY: "auto" }}
          />
          <button
            onClick={() => void send(input)}
            disabled={!input.trim() || streaming}
            className={cn(
              "flex h-10 w-10 shrink-0 items-center justify-center rounded-full transition-all",
              input.trim() && !streaming
                ? "bg-[var(--accent-primary)] text-[var(--text-inverse)] hover:opacity-90"
                : "border border-[var(--glass-border)] text-[var(--text-tertiary)] opacity-50",
            )}
          >
            <Send size={15} />
          </button>
        </div>
      </div>
    </Surface>
  );
}
