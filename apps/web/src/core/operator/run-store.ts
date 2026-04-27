import { mkdir, readFile, readdir, rename, writeFile } from 'fs/promises';
import path from 'path';
import { createCipheriv, createDecipheriv, randomBytes, randomUUID } from 'crypto';
import { env } from '@/lib/env';
import { operatorRunSchema, type CreateOperatorRunInput, type OperatorApproval, type OperatorRun } from './run-types';
import { buildOperatorRun } from './run-planner';

export interface OperatorRunStore {
  create(input: CreateOperatorRunInput): Promise<OperatorRun>;
  list(): Promise<OperatorRun[]>;
  get(runId: string): Promise<OperatorRun | null>;
  write(run: OperatorRun): Promise<void>;
}

function defaultRunsDir() {
  return path.resolve(process.cwd(), env.ELYAN_STORAGE_DIR, 'operator-runs');
}

function isMissingFileError(error: unknown) {
  return error instanceof Error && 'code' in error && (error as NodeJS.ErrnoException).code === 'ENOENT';
}

function parseOperatorRun(raw: string): OperatorRun {
  const data = JSON.parse(raw) as Record<string, unknown>;
  if (!data.continuity) {
    const updatedAt = typeof data.updatedAt === 'string' ? data.updatedAt : new Date().toISOString();
    data.continuity = {
      summary: 'Operator run continuity was created by an earlier runtime.',
      nextSteps: [],
      openItemCount: 0,
      lastActivityAt: updatedAt,
    };
  }
  if (!data.reasoning) {
    data.reasoning = {
      depth: 'standard',
      maxPasses: 3,
      halting: 'Stop when the run state and next step are clear.',
      stabilityGuard: 'Preserve existing approval and verification boundaries.',
      rationale: 'Operator run reasoning was created by an earlier runtime and normalized for v1.3.',
    };
  }
  if (!data.qualityGates) {
    data.qualityGates = [];
  }

  return operatorRunSchema.parse(data);
}

function toBase64Url(value: Buffer) {
  return value.toString('base64url');
}

function fromBase64Url(value: string) {
  return Buffer.from(value, 'base64url');
}

function getEncryptionKeyFile(runsDir: string) {
  return path.join(runsDir, '.operator-runs.key');
}

async function loadOrCreateOperatorRunKey(runsDir: string) {
  const keyPath = getEncryptionKeyFile(runsDir);

  try {
    const raw = await readFile(keyPath, 'utf8');
    const key = raw.trim();
    if (!key) {
      throw new Error('empty operator run encryption key');
    }

    return fromBase64Url(key);
  } catch (error) {
    if (!isMissingFileError(error)) {
      throw error;
    }

    await mkdir(runsDir, { recursive: true });
    const key = randomBytes(32);
    await writeFile(keyPath, `${toBase64Url(key)}\n`, { encoding: 'utf8', mode: 0o600 });
    return key;
  }
}

async function decodeOperatorRunPayload(raw: string, runsDir: string): Promise<{ run: OperatorRun; legacyPlaintext: boolean }> {
  if (!raw.startsWith('v1.')) {
    return {
      run: parseOperatorRun(raw),
      legacyPlaintext: true,
    };
  }

  const [, ivPart, encryptedPart, tagPart] = raw.trim().split('.');
  if (!ivPart || !encryptedPart || !tagPart) {
    throw new Error('Encrypted operator run payload is invalid');
  }

  const key = await loadOrCreateOperatorRunKey(runsDir);
  const decipher = createDecipheriv('aes-256-gcm', key, fromBase64Url(ivPart));
  decipher.setAuthTag(fromBase64Url(tagPart));
  const decrypted = Buffer.concat([
    decipher.update(fromBase64Url(encryptedPart)),
    decipher.final(),
  ]).toString('utf8');

  return {
    run: parseOperatorRun(decrypted),
    legacyPlaintext: false,
  };
}

async function encodeOperatorRunPayload(run: OperatorRun, runsDir: string) {
  const key = await loadOrCreateOperatorRunKey(runsDir);
  const iv = randomBytes(12);
  const cipher = createCipheriv('aes-256-gcm', key, iv);
  const encrypted = Buffer.concat([cipher.update(JSON.stringify(operatorRunSchema.parse(run)), 'utf8'), cipher.final()]);
  const tag = cipher.getAuthTag();
  return `v1.${toBase64Url(iv)}.${toBase64Url(encrypted)}.${toBase64Url(tag)}`;
}

export class FileOperatorRunStore implements OperatorRunStore {
  constructor(private readonly runsDir = defaultRunsDir()) {}

  async create(input: CreateOperatorRunInput): Promise<OperatorRun> {
    const run = buildOperatorRun(input);
    await this.write(run);
    return run;
  }

  async list(): Promise<OperatorRun[]> {
    let entries: string[];
    try {
      entries = await readdir(this.runsDir);
    } catch (error) {
      if (isMissingFileError(error)) {
        return [];
      }
      throw error;
    }

    const runs = await Promise.all(
      entries
        .filter((entry) => entry.endsWith('.json'))
        .map(async (entry) => {
          const raw = await readFile(path.join(this.runsDir, entry), 'utf8');
          const decoded = await decodeOperatorRunPayload(raw, this.runsDir);
          if (decoded.legacyPlaintext) {
            await this.write(decoded.run);
          }
          return decoded.run;
        })
    );

    return runs.sort((left, right) => right.createdAt.localeCompare(left.createdAt));
  }

  async get(runId: string): Promise<OperatorRun | null> {
    try {
      const raw = await readFile(this.runPath(runId), 'utf8');
      const decoded = await decodeOperatorRunPayload(raw, this.runsDir);
      if (decoded.legacyPlaintext) {
        await this.write(decoded.run);
      }
      return decoded.run;
    } catch (error) {
      if (isMissingFileError(error)) {
        return null;
      }
      throw error;
    }
  }

  async write(run: OperatorRun): Promise<void> {
    const parsed = operatorRunSchema.parse(run);
    await mkdir(this.runsDir, { recursive: true });
    const tempPath = path.join(this.runsDir, `${parsed.id}.${randomUUID()}.tmp`);
    await writeFile(tempPath, `${await encodeOperatorRunPayload(parsed, this.runsDir)}\n`, 'utf8');
    await rename(tempPath, this.runPath(parsed.id));
  }

  private runPath(runId: string) {
    return path.join(this.runsDir, `${runId}.json`);
  }
}

let singletonStore: FileOperatorRunStore | null = null;

export function getOperatorRunStore() {
  if (!singletonStore) {
    singletonStore = new FileOperatorRunStore();
  }

  return singletonStore;
}

export async function listOperatorApprovals(store: OperatorRunStore = getOperatorRunStore()): Promise<OperatorApproval[]> {
  const runs = await store.list();
  return runs.flatMap((run) => run.approvals).sort((left, right) => right.requestedAt.localeCompare(left.requestedAt));
}

export async function resolveOperatorApproval(
  approvalId: string,
  status: 'approved' | 'rejected',
  resolvedBy = 'local-user',
  store: OperatorRunStore = getOperatorRunStore()
) {
  const runs = await store.list();
  const run = runs.find((candidate) => candidate.approvals.some((approval) => approval.id === approvalId));

  if (!run) {
    return null;
  }

  const resolvedAt = new Date().toISOString();
  const nextApprovals = run.approvals.map((approval) =>
    approval.id === approvalId
      ? {
          ...approval,
          status,
          resolvedAt,
          resolvedBy,
        }
      : approval
  );
  const nextSteps = run.steps.map((step) => {
    if (step.approvalId !== approvalId) {
      return step;
    }

    return {
      ...step,
      status: status === 'approved' ? 'pending' : 'blocked',
    } as const;
  });
  const hasPendingApproval = nextApprovals.some((approval) => approval.status === 'pending');
  const nextContinuitySteps = run.continuity.nextSteps.map((item) => {
    const linkedStep = nextSteps.find((step) => step.id === item.sourceStepId);
    if (!linkedStep) {
      return item;
    }

    return {
      ...item,
      status: linkedStep.status === 'blocked' ? 'blocked' : item.status === 'done' ? 'done' : 'open',
    } as const;
  });
  const nextRun: OperatorRun = {
    ...run,
    approvals: nextApprovals,
    steps: nextSteps,
    status: status === 'rejected' ? 'blocked' : hasPendingApproval ? 'blocked' : 'planned',
    updatedAt: resolvedAt,
    continuity: {
      ...run.continuity,
      nextSteps: nextContinuitySteps,
      openItemCount: nextContinuitySteps.filter((item) => item.status !== 'done').length,
      lastActivityAt: resolvedAt,
    },
    notes: [
      ...run.notes,
      `Approval ${approvalId} was ${status}.`,
    ],
  };

  await store.write(nextRun);
  return nextRun.approvals.find((approval) => approval.id === approvalId) ?? null;
}

export async function recordOperatorRunArtifact(
  runId: string,
  artifact: {
    kind: OperatorRun['artifacts'][number]['kind'];
    title: string;
    content: string;
    metadata?: Record<string, unknown>;
  },
  store: OperatorRunStore = getOperatorRunStore()
) {
  const run = await store.get(runId);

  if (!run) {
    return null;
  }

  const createdAt = new Date().toISOString();
  const pendingApprovalCount = run.approvals.filter((approval) => approval.status === 'pending').length;
  const nextQualityGates = updateQualityGates(run, artifact, createdAt);
  const failedGateCount = nextQualityGates.filter((gate) => gate.status === 'failed').length;
  const blockedGateCount = nextQualityGates.filter((gate) => gate.status === 'blocked').length;
  const pendingGateCount = nextQualityGates.filter((gate) => gate.status === 'pending').length;
  const verificationStatus =
    pendingApprovalCount > 0 || blockedGateCount > 0 || pendingGateCount > 0
      ? 'blocked'
      : failedGateCount > 0
        ? 'failed'
        : 'passed';
  const nextRun: OperatorRun = {
    ...run,
    status: verificationStatus === 'blocked' ? 'blocked' : verificationStatus === 'failed' ? 'failed' : 'completed',
    updatedAt: createdAt,
    artifacts: [
      ...run.artifacts,
      {
        id: `artifact_${randomUUID().slice(0, 8)}`,
        runId,
        kind: artifact.kind,
        title: artifact.title,
        content: artifact.content,
        createdAt,
        metadata: artifact.metadata ?? {},
      },
    ],
    verification: {
      status: verificationStatus,
      summary: summarizeVerification(verificationStatus, pendingApprovalCount, failedGateCount, blockedGateCount, pendingGateCount),
      checkedAt: createdAt,
    },
    qualityGates: nextQualityGates,
    continuity: {
      ...run.continuity,
      openItemCount: run.continuity.nextSteps.filter((item) => item.status !== 'done').length,
      lastActivityAt: createdAt,
    },
  };

  await store.write(nextRun);
  return nextRun;
}

function updateQualityGates(
  run: OperatorRun,
  artifact: {
    kind: OperatorRun['artifacts'][number]['kind'];
    title: string;
    content: string;
    metadata?: Record<string, unknown>;
  },
  checkedAt: string
): OperatorRun['qualityGates'] {
  const sourceCount = Number(artifact.metadata?.sourceCount ?? 0);
  const unavailable = artifact.metadata?.unavailable === true;
  const checksPassed = artifact.metadata?.checksPassed === true;
  const inspected = artifact.metadata?.repoInspected === true;

  return run.qualityGates.map((gate) => {
    if (run.mode === 'research' && gate.title === 'Source coverage') {
      const passed = sourceCount > 0 || unavailable;
      return {
        ...gate,
        status: passed ? 'passed' : 'failed',
        evidence: passed
          ? sourceCount > 0
            ? `${sourceCount} source(s) recorded.`
            : 'Live evidence unavailable state was recorded.'
          : 'No sources or unavailable-state explanation were recorded.',
        checkedAt,
      };
    }

    if (run.mode === 'research' && gate.title === 'Citation integrity') {
      const hasCitation = /\[[0-9]+\]/.test(artifact.content) || unavailable;
      return {
        ...gate,
        status: hasCitation ? 'passed' : 'failed',
        evidence: hasCitation ? 'Citation markers or unavailable-state explanation were found.' : 'No citation markers were found.',
        checkedAt,
      };
    }

    if (run.mode === 'code' && gate.title === 'Repository inspection') {
      return {
        ...gate,
        status: inspected ? 'passed' : gate.status,
        evidence: inspected ? 'Repository inspection metadata was recorded.' : gate.evidence,
        checkedAt: inspected ? checkedAt : gate.checkedAt,
      };
    }

    if (run.mode === 'code' && gate.title === 'Approval boundary') {
      const hasPendingApproval = run.approvals.some((approval) => approval.status === 'pending');
      return {
        ...gate,
        status: hasPendingApproval ? 'blocked' : 'passed',
        evidence: hasPendingApproval ? 'Side-effectful execution is still waiting for approval.' : 'No pending approval remains.',
        checkedAt,
      };
    }

    if (run.mode === 'code' && gate.title === 'Verification path') {
      return {
        ...gate,
        status: checksPassed ? 'passed' : gate.status,
        evidence: checksPassed ? 'Focused checks were recorded as passed.' : gate.evidence,
        checkedAt: checksPassed ? checkedAt : gate.checkedAt,
      };
    }

    if (run.mode === 'cowork' && gate.title === 'Role artifacts') {
      const hasCoworkArtifact = ['plan', 'execution', 'review', 'verification', 'summary'].includes(artifact.kind);
      return {
        ...gate,
        status: hasCoworkArtifact ? 'passed' : gate.status,
        evidence: hasCoworkArtifact ? `Recorded ${artifact.kind} artifact.` : gate.evidence,
        checkedAt: hasCoworkArtifact ? checkedAt : gate.checkedAt,
      };
    }

    if (run.mode === 'cowork' && gate.title === 'Local memory boundary') {
      return {
        ...gate,
        status: artifact.metadata?.sharedToHosted === true ? 'failed' : 'passed',
        evidence: artifact.metadata?.sharedToHosted === true
          ? 'Artifact metadata indicates hosted sharing.'
          : 'No hosted memory sharing was recorded.',
        checkedAt,
      };
    }

    return gate;
  });
}

function summarizeVerification(
  status: OperatorRun['verification']['status'],
  pendingApprovalCount: number,
  failedGateCount: number,
  blockedGateCount: number,
  pendingGateCount: number
) {
  if (pendingApprovalCount > 0) {
    return 'Run is waiting for approval before side-effectful execution can continue.';
  }

  if (blockedGateCount > 0) {
    return `${blockedGateCount} quality gate(s) are blocked.`;
  }

  if (pendingGateCount > 0) {
    return `${pendingGateCount} quality gate(s) still need evidence.`;
  }

  if (failedGateCount > 0) {
    return `${failedGateCount} quality gate(s) failed.`;
  }

  if (status === 'passed') {
    return 'Run produced an inspectable artifact and passed its current quality gates.';
  }

  return 'Verification has not run yet.';
}
