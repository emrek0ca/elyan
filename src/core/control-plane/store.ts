import { mkdir, readFile, writeFile, rename } from 'fs/promises';
import path from 'path';
import { randomUUID } from 'crypto';
import { createDefaultControlPlaneState, migrateControlPlaneState } from './defaults';
import type { ControlPlaneState } from './types';
import { ControlPlaneStoreError } from './errors';

export interface ControlPlaneStateStore {
  readonly kind: 'file' | 'postgres';
  read(): Promise<ControlPlaneState>;
  write(state: ControlPlaneState): Promise<void>;
}

function isMissingFileError(error: unknown): boolean {
  return error instanceof Error && 'code' in error && (error as NodeJS.ErrnoException).code === 'ENOENT';
}

export class FileControlPlaneStateStore implements ControlPlaneStateStore {
  readonly kind = 'file' as const;

  constructor(private readonly statePath: string) {}

  async read(): Promise<ControlPlaneState> {
    try {
      const raw = await readFile(this.statePath, 'utf8');
      const parsed = migrateControlPlaneState(JSON.parse(raw));

      if (parsed.version !== 3) {
        throw new ControlPlaneStoreError('Control-plane migration failed');
      }

      const rawParsed = JSON.parse(raw) as { version?: number };
      if (rawParsed.version === 1) {
        await this.write(parsed);
      }

      return parsed;
    } catch (error) {
      if (isMissingFileError(error)) {
        const state = createDefaultControlPlaneState();
        await this.write(state);
        return state;
      }

      const message = error instanceof Error ? error.message : 'unknown control plane read failure';
      throw new ControlPlaneStoreError(`Failed to read control-plane state: ${message}`);
    }
  }

  async write(state: ControlPlaneState): Promise<void> {
    try {
      await mkdir(path.dirname(this.statePath), { recursive: true });

      const tempPath = `${this.statePath}.${randomUUID()}.tmp`;
      await writeFile(tempPath, `${JSON.stringify(state, null, 2)}\n`, 'utf8');
      await rename(tempPath, this.statePath);
    } catch (error) {
      const message = error instanceof Error ? error.message : 'unknown control plane write failure';
      throw new ControlPlaneStoreError(`Failed to write control-plane state: ${message}`);
    }
  }
}
