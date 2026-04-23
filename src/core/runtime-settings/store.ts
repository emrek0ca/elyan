import { mkdir, readFile, writeFile, rename } from 'fs/promises';
import { readFileSync } from 'fs';
import path from 'path';
import { randomUUID } from 'crypto';
import { env } from '@/lib/env';
import { resolveRuntimeSettingsPath } from '@/lib/runtime-paths';
import {
  runtimeSettingsSchema,
  type RuntimeSettings,
  type RuntimeSettingsPatch,
} from './types';

export interface RuntimeSettingsStore {
  read(): Promise<RuntimeSettings>;
  write(state: RuntimeSettings): Promise<void>;
  patch(patch: RuntimeSettingsPatch): Promise<RuntimeSettings>;
}

function createDefaultRuntimeSettings(): RuntimeSettings {
  return runtimeSettingsSchema.parse({
    version: 1,
    routing: {
      routingMode: 'local_first',
      searchEnabled: true,
    },
    channels: {
      telegram: {
        enabled: false,
        mode: 'polling',
        webhookPath: '/api/channels/telegram/webhook',
      },
      whatsappCloud: {
        enabled: false,
        webhookPath: '/api/channels/whatsapp/webhook',
      },
      whatsappBaileys: {
        enabled: false,
        sessionPath: 'storage/channels/whatsapp-baileys.json',
      },
      imessage: {
        enabled: false,
        mode: 'bluebubbles',
        webhookPath: '/api/channels/imessage/bluebubbles/webhook',
      },
    },
    voice: {
      enabled: false,
      wakeWord: 'elyan',
      language: 'en',
      sampleRate: 16000,
    },
    mcp: {
      servers: [],
    },
  });
}

function isMissingFileError(error: unknown): boolean {
  return error instanceof Error && 'code' in error && (error as NodeJS.ErrnoException).code === 'ENOENT';
}

function deepMerge<T extends Record<string, unknown>>(base: T, patch: Partial<T>): T {
  const result = { ...base } as Record<string, unknown>;

  for (const [key, value] of Object.entries(patch)) {
    if (value === undefined) {
      continue;
    }

    const current = result[key];
    if (
      current &&
      value &&
      typeof current === 'object' &&
      typeof value === 'object' &&
      !Array.isArray(current) &&
      !Array.isArray(value)
    ) {
      result[key] = deepMerge(current as Record<string, unknown>, value as Record<string, unknown>);
      continue;
    }

    result[key] = value as unknown;
  }

  return result as T;
}

export class FileRuntimeSettingsStore implements RuntimeSettingsStore {
  constructor(private readonly statePath: string) {}

  async read(): Promise<RuntimeSettings> {
    try {
      const raw = await readFile(this.statePath, 'utf8');
      return runtimeSettingsSchema.parse(JSON.parse(raw));
    } catch (error) {
      if (isMissingFileError(error)) {
        const state = createDefaultRuntimeSettings();
        await this.write(state);
        return state;
      }

      const message = error instanceof Error ? error.message : 'unknown runtime settings read failure';
      throw new Error(`Failed to read runtime settings: ${message}`);
    }
  }

  async write(state: RuntimeSettings): Promise<void> {
    await mkdir(path.dirname(this.statePath), { recursive: true });
    const tempPath = `${this.statePath}.${randomUUID()}.tmp`;
    await writeFile(tempPath, `${JSON.stringify(state, null, 2)}\n`, 'utf8');
    await rename(tempPath, this.statePath);
  }

  async patch(patch: RuntimeSettingsPatch): Promise<RuntimeSettings> {
    const current = await this.read();
    const next = runtimeSettingsSchema.parse(deepMerge(current, patch as Record<string, unknown>));
    await this.write(next);
    return next;
  }
}

export function getRuntimeSettingsPath() {
  return resolveRuntimeSettingsPath(env.ELYAN_RUNTIME_SETTINGS_PATH, process.cwd());
}

let singletonStore: FileRuntimeSettingsStore | null = null;

export function getRuntimeSettingsStore() {
  if (!singletonStore) {
    singletonStore = new FileRuntimeSettingsStore(getRuntimeSettingsPath());
  }

  return singletonStore;
}

export async function readRuntimeSettings() {
  return getRuntimeSettingsStore().read();
}

export function readRuntimeSettingsSync(): RuntimeSettings {
  try {
    const raw = readFileSync(getRuntimeSettingsPath(), 'utf8');
    return runtimeSettingsSchema.parse(JSON.parse(raw));
  } catch (error) {
    if (isMissingFileError(error)) {
      return createDefaultRuntimeSettings();
    }

    const message = error instanceof Error ? error.message : 'unknown runtime settings read failure';
    throw new Error(`Failed to read runtime settings: ${message}`);
  }
}
