import { asRecord as readRecord } from "../../lib/record.js";
/**
 * Masaüstü RUNTIME ERİŞİM DURUMUNUN SUNUCU OTORİTESİ.
 *
 * Bu dosyadan önce erişim durumu yalnız runtime'ın gönderdiği ACK'ten
 * türetiliyordu: gövdedeki `commandId`, `action` ve `expiresAt` doğrulanmadan
 * kabul ediliyor, `heartbeat` ise `capability_states` sütununu runtime'ın
 * beyan ettiği içerikle tamamen değiştiriyordu. Bu iki yol birlikte üç somut
 * açık üretiyordu:
 *
 *   1. Revoke'tan sonra gelen GEÇ bir grant ACK'i erişimi yeniden açabiliyordu.
 *   2. Runtime kendi `expiresAt` değerini uzatabiliyordu.
 *   3. Runtime, heartbeat handshake'inde `runtime.access.session.v1` anahtarını
 *      kendisi yazarak hiç komut verilmemişken erişimi "açık" gösterebiliyordu.
 *
 * Burada erişim durumu sunucunun verdiği komuta bağlanır: her komut monotonik
 * bir `revision` alır, ACK yalnız bekleyen komutla eşleşirse uygulanır ve süre
 * her zaman sunucunun `issuedAt + ttl` tavanına kırpılır.
 */

export const RUNTIME_ACCESS_STATE_KEY = "runtime.access.session.v1";
export const RUNTIME_ACCESS_STATE_CONTRACT = "elyan.runtime_access_state.v1";

/**
 * Runtime'ın handshake'te YAZAMAYACAĞI anahtarlar. Bu anahtarların tek yazarı
 * sunucudur; runtime beyanı sessizce düşürülür.
 */
export const SERVER_OWNED_CAPABILITY_STATE_KEYS: readonly string[] = [
  RUNTIME_ACCESS_STATE_KEY,
];

/** Oturum erişiminin sunucu tarafındaki tavanı. Runtime bunu uzatamaz. */
export const RUNTIME_ACCESS_SESSION_TTL_SECONDS = 3600;

export type RuntimeAccessAction = "grant_session" | "revoke";
export type RuntimeAccessAckState = "applied" | "rejected" | "failed";

export type RuntimeAccessPendingCommand = {
  commandId: string;
  action: RuntimeAccessAction;
  revision: number;
  issuedAt: string;
  expectedExpiresAt: string | null;
};

export type RuntimeAccessState = {
  contract: typeof RUNTIME_ACCESS_STATE_CONTRACT;
  mode: "session" | "off";
  active: boolean;
  revision: number;
  commandId: string | null;
  action: RuntimeAccessAction | null;
  state: RuntimeAccessAckState | null;
  expiresAt: string | null;
  updatedAt: string;
  message?: string;
  pending: RuntimeAccessPendingCommand | null;
};

function readIsoString(value: unknown): string | null {
  if (typeof value !== "string") return null;
  const parsed = Date.parse(value);
  return Number.isFinite(parsed) ? new Date(parsed).toISOString() : null;
}

function readAction(value: unknown): RuntimeAccessAction | null {
  return value === "grant_session" || value === "revoke" ? value : null;
}

function readPending(value: unknown): RuntimeAccessPendingCommand | null {
  const record = readRecord(value);
  if (!record) return null;
  const commandId = typeof record.commandId === "string" ? record.commandId : null;
  const action = readAction(record.action);
  const revision = Number(record.revision);
  const issuedAt = readIsoString(record.issuedAt);
  if (!commandId || !action || !Number.isFinite(revision) || !issuedAt) return null;
  return {
    commandId,
    action,
    revision,
    issuedAt,
    expectedExpiresAt: readIsoString(record.expectedExpiresAt),
  };
}

export function emptyRuntimeAccessState(now = new Date()): RuntimeAccessState {
  return {
    contract: RUNTIME_ACCESS_STATE_CONTRACT,
    mode: "off",
    active: false,
    revision: 0,
    commandId: null,
    action: null,
    state: null,
    expiresAt: null,
    updatedAt: now.toISOString(),
    pending: null,
  };
}

/**
 * Saklanan ham JSON'dan durumu okur. Süresi geçmiş bir grant burada ölür:
 * "aktif" alanı yalnız `expiresAt` gelecekteyken doğrudur, böylece süresi
 * dolmuş bir kayıt yanlışlıkla açık erişim gibi okunamaz.
 */
export function readRuntimeAccessState(
  value: unknown,
  now = new Date(),
): RuntimeAccessState {
  const record = readRecord(value);
  if (!record) return emptyRuntimeAccessState(now);
  const revision = Number.isFinite(Number(record.revision)) ? Number(record.revision) : 0;
  const expiresAt = readIsoString(record.expiresAt);
  const storedActive = record.active === true;
  const active = storedActive && Boolean(expiresAt) && Date.parse(expiresAt!) > now.getTime();
  return {
    contract: RUNTIME_ACCESS_STATE_CONTRACT,
    mode: active ? "session" : "off",
    active,
    revision,
    commandId: typeof record.commandId === "string" ? record.commandId : null,
    action: readAction(record.action),
    state:
      record.state === "applied" || record.state === "rejected" || record.state === "failed"
        ? record.state
        : null,
    expiresAt: active ? expiresAt : null,
    updatedAt: readIsoString(record.updatedAt) ?? now.toISOString(),
    ...(typeof record.message === "string" ? { message: record.message } : {}),
    pending: readPending(record.pending),
  };
}

export function readRuntimeAccessStateFromCapabilityStates(
  capabilityStates: unknown,
  now = new Date(),
): RuntimeAccessState {
  const record = readRecord(capabilityStates);
  return readRuntimeAccessState(record?.[RUNTIME_ACCESS_STATE_KEY], now);
}

/**
 * Runtime'ın beyan ettiği capability state haritasından sunucuya ait
 * anahtarları atar. Handshake bu anahtarlara asla dokunamaz.
 */
export function stripServerOwnedCapabilityStates(
  capabilityStates: Record<string, unknown>,
): Record<string, unknown> {
  const filtered: Record<string, unknown> = { ...capabilityStates };
  for (const key of SERVER_OWNED_CAPABILITY_STATE_KEYS) {
    delete filtered[key];
  }
  return filtered;
}

/** Yeni komut için bekleyen kaydı üretir; erişim durumunu HENÜZ değiştirmez. */
export function withPendingRuntimeAccessCommand(
  current: RuntimeAccessState,
  input: {
    commandId: string;
    action: RuntimeAccessAction;
    now: Date;
    ttlSeconds?: number;
  },
): { next: RuntimeAccessState; pending: RuntimeAccessPendingCommand } {
  const ttlSeconds = input.ttlSeconds ?? RUNTIME_ACCESS_SESSION_TTL_SECONDS;
  const pending: RuntimeAccessPendingCommand = {
    commandId: input.commandId,
    action: input.action,
    revision: current.revision + 1,
    issuedAt: input.now.toISOString(),
    expectedExpiresAt:
      input.action === "grant_session"
        ? new Date(input.now.getTime() + ttlSeconds * 1000).toISOString()
        : null,
  };
  return {
    next: { ...current, pending, updatedAt: input.now.toISOString() },
    pending,
  };
}

export type RuntimeAccessAckDecision =
  | { applied: true; next: RuntimeAccessState }
  | {
      applied: false;
      reason:
        | "no_pending_command"
        | "command_id_mismatch"
        | "action_mismatch"
        | "superseded_revision";
    };

/**
 * ACK'i BEKLEYEN komutla eşleştirir.
 *
 * Eşleşme dört alanı birden ister: bekleyen bir komut olmalı, `commandId` ve
 * `action` birebir tutmalı, ve bekleyen komutun revizyonu hâlâ en güncel
 * olmalı. Bu yüzden revoke'tan sonra gelen geç bir grant ACK'i eşleşemez;
 * revoke yeni bir revizyon yazdığı anda eski komut bekleyen olmaktan çıkar.
 */
export function applyRuntimeAccessAck(
  current: RuntimeAccessState,
  input: {
    commandId: string;
    action: RuntimeAccessAction;
    state: RuntimeAccessAckState;
    expiresAt?: string | null;
    message?: string;
    now: Date;
  },
): RuntimeAccessAckDecision {
  const pending = current.pending;
  if (!pending) return { applied: false, reason: "no_pending_command" };
  if (pending.commandId !== input.commandId) {
    return { applied: false, reason: "command_id_mismatch" };
  }
  if (pending.action !== input.action) {
    return { applied: false, reason: "action_mismatch" };
  }
  if (pending.revision !== current.revision + 1) {
    return { applied: false, reason: "superseded_revision" };
  }

  const granted = input.state === "applied" && input.action === "grant_session";
  const ceiling = pending.expectedExpiresAt
    ? Date.parse(pending.expectedExpiresAt)
    : null;
  // Runtime'ın bildirdiği süre yalnız KISALTABİLİR. Bildirilmemiş, bozuk veya
  // tavanı aşan bir değerde sunucunun `issuedAt + ttl` tavanı geçerlidir.
  const claimed = readIsoString(input.expiresAt ?? null);
  const claimedMs = claimed ? Date.parse(claimed) : null;
  const effectiveMs =
    ceiling === null
      ? null
      : claimedMs !== null && claimedMs < ceiling
        ? claimedMs
        : ceiling;
  const active = granted && effectiveMs !== null && effectiveMs > input.now.getTime();

  return {
    applied: true,
    next: {
      contract: RUNTIME_ACCESS_STATE_CONTRACT,
      mode: active ? "session" : "off",
      active,
      revision: pending.revision,
      commandId: pending.commandId,
      action: pending.action,
      state: input.state,
      expiresAt: active ? new Date(effectiveMs!).toISOString() : null,
      updatedAt: input.now.toISOString(),
      ...(input.message ? { message: input.message } : {}),
      pending: null,
    },
  };
}

/** Sokete teslim edilemeyen komutun bekleyen kaydını düşürür. */
export function clearPendingRuntimeAccessCommand(
  current: RuntimeAccessState,
  commandId: string,
  now = new Date(),
): RuntimeAccessState {
  if (current.pending?.commandId !== commandId) return current;
  return { ...current, pending: null, updatedAt: now.toISOString() };
}
