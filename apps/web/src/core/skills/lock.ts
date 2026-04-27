import { existsSync } from 'fs';
import { readFile } from 'fs/promises';
import path from 'path';
import { z } from 'zod';
import { skillInstallationRecordSchema, type SkillInstallationRecord } from './types';

const skillLockEntrySchema = z.object({
  source: z.string().min(1),
  sourceType: z.string().min(1),
  computedHash: z.string().min(1),
});

const skillLockFileSchema = z.object({
  version: z.number().int().positive(),
  skills: z.record(z.string().min(1), skillLockEntrySchema),
});

export type SkillLockDiscovery = {
  attempted: boolean;
  status: 'skipped' | 'ready' | 'degraded' | 'unavailable';
  error?: string;
};

export type SkillLockLoadResult = {
  installed: SkillInstallationRecord[];
  discovery: SkillLockDiscovery;
};

function describeError(error: unknown) {
  if (error instanceof Error) {
    return error.message;
  }

  return 'unknown skill lock failure';
}

export async function readSkillInstallations(lockPath = path.resolve(process.cwd(), 'skills-lock.json')): Promise<SkillLockLoadResult> {
  if (!existsSync(lockPath)) {
    return {
      installed: [],
      discovery: {
        attempted: false,
        status: 'skipped',
      },
    };
  }

  try {
    const raw = await readFile(lockPath, 'utf8');
    const parsed = skillLockFileSchema.parse(JSON.parse(raw));
    const installed = Object.entries(parsed.skills).map(([id, entry]) =>
      skillInstallationRecordSchema.parse({
        id,
        source: entry.source,
        sourceType: entry.sourceType,
        computedHash: entry.computedHash,
        version: 'locked',
      })
    );

    return {
      installed,
      discovery: {
        attempted: true,
        status: 'ready',
      },
    };
  } catch (error) {
    return {
      installed: [],
      discovery: {
        attempted: true,
        status: 'unavailable',
        error: describeError(error),
      },
    };
  }
}

