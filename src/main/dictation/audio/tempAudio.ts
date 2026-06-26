/**
 * Temporary audio file manager.
 * Creates and deletes temp WAV files used during transcription.
 * Raw audio is NOT persisted beyond the transcription session.
 */

import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import crypto from 'node:crypto';

export function createTempAudioPath(): string {
  const id = crypto.randomUUID().replace(/-/g, '').slice(0, 12);
  return path.join(os.tmpdir(), `elyan-dictation-${id}.wav`);
}

export function deleteTempAudio(filePath: string): void {
  try {
    if (fs.existsSync(filePath)) {
      fs.unlinkSync(filePath);
    }
  } catch {
    // Ignore deletion errors — file may already be removed
  }
}

export function cleanStaleAudioFiles(): void {
  try {
    const tmpDir = os.tmpdir();
    const files = fs.readdirSync(tmpDir);
    for (const file of files) {
      if (file.startsWith('elyan-dictation-') && file.endsWith('.wav')) {
        const filePath = path.join(tmpDir, file);
        try {
          const stat = fs.statSync(filePath);
          // Delete files older than 10 minutes
          if (Date.now() - stat.mtimeMs > 10 * 60 * 1000) {
            fs.unlinkSync(filePath);
          }
        } catch {
          // ignore per-file errors
        }
      }
    }
  } catch {
    // ignore
  }
}
