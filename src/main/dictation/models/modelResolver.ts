/**
 * Model resolver — locates whisper.cpp model files on disk.
 * Model dir: {userData}/models/whisper/
 */

import fs from 'node:fs';
import path from 'node:path';
import { app } from 'electron';
import { WHISPER_MODELS, WHISPER_MODEL_URLS, type DictationModelQuality } from '../types';

export interface ModelResolveResult {
  available: boolean;
  path: string | null;
  expectedPath: string;
  downloadUrl: string;
}

export function getModelDir(): string {
  return path.join(app.getPath('userData'), 'models', 'whisper');
}

export function resolveModel(quality: DictationModelQuality): ModelResolveResult {
  const modelDir = getModelDir();
  const fileName = WHISPER_MODELS[quality];
  const expectedPath = path.join(modelDir, fileName);
  const available = fs.existsSync(expectedPath);

  return {
    available,
    path: available ? expectedPath : null,
    expectedPath,
    downloadUrl: WHISPER_MODEL_URLS[quality],
  };
}

export function ensureModelDir(): void {
  const dir = getModelDir();
  if (!fs.existsSync(dir)) {
    fs.mkdirSync(dir, { recursive: true });
  }
}
