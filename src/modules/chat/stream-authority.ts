// Chat stream otorite sözleşmesi.
//
// Mobil, aynı assistantMessageId için iki kaynaktan güncelleme alır: volatile
// SSE stream (delta/heartbeat/ACK) ve kalıcı lifecycle event'leri
// (message.completed, chat.message.updated). Ağ/fanout sırası garanti
// olmadığından "completed" mobil'e ulaştıktan SONRA eski bir running/ACK
// snapshot'ı gelebilir ve final cevabı geri "Yanıt hazırlanıyor."a çevirir.
//
// Sözleşme:
// 1. Event sırası (`eventRank`) ile mesaj lifecycle durumu
//    (`messageStatusRank`) ayrı eksenlerdir. Waiting approval gibi bir
//    lifecycle durumu, sonradan gelen metin deltalarını susturamaz.
// 2. Backend, kalıcı final yazıldıktan sonra aynı mesaj için volatile event
//    publish etmez (terminal fence).

export const TERMINAL_CHAT_STREAM_EVENT_RANK = 90;
export const TERMINAL_CHAT_MESSAGE_STATUS_RANK = 90;
// Eski import'lar ve dış sözleşme için geriye dönük isim.
export const TERMINAL_CHAT_STREAM_STATUS_RANK = TERMINAL_CHAT_STREAM_EVENT_RANK;

const CHAT_STREAM_EVENT_RANKS: Record<string, number> = {
  heartbeat: 10,
  "message.created": 20,
  "block.preview": 30,
  "message.delta": 30,
  "chat.message.updated": 30,
  "usage.final": 40,
  "message.completed": TERMINAL_CHAT_STREAM_EVENT_RANK,
  "message.error": TERMINAL_CHAT_STREAM_EVENT_RANK,
};

const CHAT_MESSAGE_STATUS_RANKS: Record<string, number> = {
  queued: 20,
  running: 30,
  waiting_approval: 50,
  completed: TERMINAL_CHAT_MESSAGE_STATUS_RANK,
  failed: TERMINAL_CHAT_MESSAGE_STATUS_RANK,
  canceled: TERMINAL_CHAT_MESSAGE_STATUS_RANK,
};

export function chatStreamEventStatusRank(event: string): number {
  return CHAT_STREAM_EVENT_RANKS[event] ?? 30;
}

export function chatMessageStatusRank(status: string): number {
  return CHAT_MESSAGE_STATUS_RANKS[status] ?? 30;
}

export function isTerminalChatStreamEvent(event: string): boolean {
  return chatStreamEventStatusRank(event) >= TERMINAL_CHAT_STREAM_EVENT_RANK;
}

export function isTerminalChatMessageStatus(status: string): boolean {
  return chatMessageStatusRank(status) >= TERMINAL_CHAT_MESSAGE_STATUS_RANK;
}

// Süreç içi terminal fence: kalıcı final (completed/error) yazılan mesajlar.
// Amaç, aynı worker'da hâlâ uçuşta olan heartbeat/delta timer'larının final
// SONRASI volatile event basmasını engellemek. Süreçler arası sıralamayı
// statusRank + DB'deki `status <> 'completed'` CAS'ı çözer; bu fence yalnız
// yerel yarışları kapatan ucuz bir ek kattır.
const FENCE_TTL_MS = 10 * 60_000;
const FENCE_MAX_ENTRIES = 5_000;
const terminalMessageFence = new Map<string, number>();

function pruneFence(now: number) {
  for (const [id, fencedAt] of terminalMessageFence) {
    if (now - fencedAt > FENCE_TTL_MS) {
      terminalMessageFence.delete(id);
    }
  }
  if (terminalMessageFence.size > FENCE_MAX_ENTRIES) {
    const overflow = terminalMessageFence.size - FENCE_MAX_ENTRIES;
    let removed = 0;
    for (const id of terminalMessageFence.keys()) {
      if (removed >= overflow) break;
      terminalMessageFence.delete(id);
      removed += 1;
    }
  }
}

export function markAssistantMessageTerminal(messageId: string): boolean {
  if (!messageId) return false;
  const now = Date.now();
  pruneFence(now);
  const fencedAt = terminalMessageFence.get(messageId);
  if (fencedAt != null && now - fencedAt <= FENCE_TTL_MS) {
    return false;
  }
  terminalMessageFence.set(messageId, now);
  return true;
}

export function releaseAssistantMessageTerminal(messageId: string) {
  if (!messageId) return;
  terminalMessageFence.delete(messageId);
}

export function isAssistantMessageTerminallyFenced(messageId: string): boolean {
  if (!messageId) return false;
  const fencedAt = terminalMessageFence.get(messageId);
  if (fencedAt == null) return false;
  if (Date.now() - fencedAt > FENCE_TTL_MS) {
    terminalMessageFence.delete(messageId);
    return false;
  }
  return true;
}

export function resetAssistantMessageTerminalFenceForTests() {
  terminalMessageFence.clear();
}
