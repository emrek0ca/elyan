import { mkdir, readFile, writeFile } from 'fs/promises';
import path from 'path';
import { readRuntimeSettingsSync } from '@/core/runtime-settings';

type BaileysSessionState = {
  status: 'not_configured' | 'pending_pairing' | 'paired' | 'disconnected';
  updatedAt: string;
  qr?: string;
  note?: string;
};

function resolveSessionPath() {
  const settings = readRuntimeSettingsSync();
  const sessionPath = settings.channels.whatsappBaileys.sessionPath;
  return path.isAbsolute(sessionPath) ? sessionPath : path.resolve(process.cwd(), sessionPath);
}

async function readSessionState(): Promise<BaileysSessionState | null> {
  try {
    const raw = await readFile(resolveSessionPath(), 'utf8');
    return JSON.parse(raw) as BaileysSessionState;
  } catch {
    return null;
  }
}

export async function writeBaileysSessionState(state: BaileysSessionState) {
  const sessionPath = resolveSessionPath();
  await mkdir(path.dirname(sessionPath), { recursive: true });
  await writeFile(sessionPath, `${JSON.stringify(state, null, 2)}\n`, 'utf8');
  return state;
}

export function getWhatsappBaileysStatus() {
  const settings = readRuntimeSettingsSync();
  return {
    configured: settings.channels.whatsappBaileys.enabled,
    enabled: settings.channels.whatsappBaileys.enabled,
    sessionPath: settings.channels.whatsappBaileys.sessionPath,
    costProfile: 'local_unofficial_best_effort',
    supportLevel: 'best_effort_unofficial',
  };
}

export async function probeWhatsappBaileysSession() {
  const settings = readRuntimeSettingsSync();
  const state = await readSessionState();
  return {
    ok: Boolean(settings.channels.whatsappBaileys.enabled && state?.status === 'paired'),
    configured: settings.channels.whatsappBaileys.enabled,
    status: state?.status ?? 'not_configured',
    sessionPath: settings.channels.whatsappBaileys.sessionPath,
    warning: 'WhatsApp Baileys is local and unofficial; use WhatsApp Cloud for official business-critical delivery.',
  };
}
