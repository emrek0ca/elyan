import { mkdir, stat, writeFile, appendFile } from 'fs/promises';
import path from 'path';
import { randomUUID } from 'crypto';
import { env } from '@/lib/env';
import type { LocalAgentAction, LocalAgentDecision } from './types';

export function createLocalAgentRunId() {
  return `local_${Date.now()}_${randomUUID().slice(0, 8)}`;
}

export function resolveEvidenceDir(runId: string, evidenceDir = 'storage/evidence') {
  const relativeEvidenceDir = evidenceDir.startsWith(`storage${path.sep}`)
    ? path.relative('storage', evidenceDir)
    : evidenceDir;
  const baseDir = path.isAbsolute(evidenceDir)
    ? evidenceDir
    : path.resolve(process.cwd(), env.ELYAN_STORAGE_DIR, relativeEvidenceDir);
  return path.join(baseDir, runId);
}

async function pathSnapshot(targetPath?: string) {
  if (!targetPath) {
    return null;
  }

  try {
    const info = await stat(targetPath);
    return {
      exists: true,
      type: info.isDirectory() ? 'directory' : info.isFile() ? 'file' : 'other',
      size: info.size,
      mtimeMs: info.mtimeMs,
    };
  } catch {
    return {
      exists: false,
    };
  }
}

export async function writeLocalAgentEvidence(input: {
  runId: string;
  evidenceDir?: string;
  action: LocalAgentAction;
  decision: LocalAgentDecision;
  phase: 'started' | 'completed' | 'failed' | 'rejected';
  output?: unknown;
  error?: string;
}) {
  const dir = resolveEvidenceDir(input.runId, input.evidenceDir);
  await mkdir(dir, { recursive: true });
  const record = {
    timestamp: new Date().toISOString(),
    phase: input.phase,
    actionType: input.action.type,
    action: {
      ...input.action,
      content: 'content' in input.action ? `[redacted:${input.action.content.length}]` : undefined,
    },
    decision: input.decision,
    snapshot: await pathSnapshot(input.decision.normalizedPath),
    output: input.output,
    error: input.error,
  };

  await appendFile(path.join(dir, 'events.jsonl'), `${JSON.stringify(record)}\n`, 'utf8');
  await writeFile(path.join(dir, 'latest.json'), `${JSON.stringify(record, null, 2)}\n`, 'utf8');
}
