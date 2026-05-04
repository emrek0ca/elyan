import { mkdir, mkdtemp, readFile, rm, writeFile } from 'fs/promises';
import { tmpdir } from 'os';
import path from 'path';
import { afterEach, describe, expect, it } from 'vitest';
import {
  buildOperatorRun,
  FileOperatorRunStore,
  listOperatorApprovals,
  recordOperatorRunArtifact,
  resolveOperatorApproval,
  resolveOperatorRunMode,
} from '@/core/operator';

const tempDirs: string[] = [];

async function createTempDir() {
  const dir = await mkdtemp(path.join(tmpdir(), 'elyan-operator-runs-'));
  tempDirs.push(dir);
  return dir;
}

afterEach(async () => {
  while (tempDirs.length > 0) {
    await rm(tempDirs.pop()!, { recursive: true, force: true });
  }
});

describe('operator run planning', () => {
  it('detects code work as a guarded operator mode', () => {
    expect(resolveOperatorRunMode('inspect this repo and implement the missing tests', 'auto')).toBe('code');
  });

  it('creates research runs without fake approval requirements', () => {
    const run = buildOperatorRun({
      source: 'cli',
      text: 'research current model routing approaches with sources',
      mode: 'auto',
    });

    expect(run.mode).toBe('research');
    expect(run.status).toBe('planned');
    expect(run.approvals).toHaveLength(0);
    expect(run.qualityGates.map((gate) => gate.title)).toEqual(['Source coverage', 'Citation integrity']);
    expect(run.artifacts[0]?.content).toContain('Collect sources');
    expect(run.artifacts[0]?.content).toContain('Evidence requirement: sources or an honest unavailable-state explanation.');
  });

  it('blocks coding execution behind an approval request', () => {
    const run = buildOperatorRun({
      source: 'cli',
      text: 'implement a safe patch in this repository',
      mode: 'code',
    });

    expect(run.status).toBe('blocked');
    expect(run.approvals).toHaveLength(1);
    expect(run.approvals[0]).toMatchObject({
      status: 'pending',
      riskLevel: 'write_safe',
      approvalLevel: 'CONFIRM',
    });
    expect(run.steps.some((step) => step.requiresApproval && step.approvalId === run.approvals[0]?.id)).toBe(true);
    expect(run.reasoning).toMatchObject({
      depth: 'deep',
      maxPasses: 5,
    });
    expect(run.qualityGates).toEqual(
      expect.arrayContaining([
        expect.objectContaining({ title: 'Approval boundary', status: 'blocked' }),
        expect.objectContaining({ title: 'Verification path', status: 'pending' }),
      ])
    );
    expect(run.notes.some((note) => note.includes('Adaptive reasoning profile'))).toBe(true);
    expect(run.continuity.summary).toContain('Coding run');
    expect(run.continuity.openItemCount).toBe(3);
    expect(run.continuity.nextSteps.map((item) => item.title)).toEqual([
      'Inspect repository',
      'Plan patch',
      'Verify and summarize',
    ]);
  });
});

describe('operator run store', () => {
  it('persists runs and lists newest first', async () => {
    const dir = await createTempDir();
    const store = new FileOperatorRunStore(dir);

    const first = await store.create({
      source: 'cli',
      text: 'research local-first agents with sources',
      mode: 'research',
    });
    const second = await store.create({
      source: 'cli',
      text: 'implement a repository patch',
      mode: 'code',
    });

    const runs = await store.list();

    expect(await store.get(first.id)).toMatchObject({ id: first.id, mode: 'research' });
    expect(runs.map((run) => run.id)).toEqual([second.id, first.id]);
  });

  it('stores operator runs encrypted at rest and reads them back transparently', async () => {
    const dir = await createTempDir();
    const store = new FileOperatorRunStore(dir);
    const run = await store.create({
      source: 'cli',
      text: 'research local-first agents with sources',
      mode: 'research',
    });

    const raw = await readFile(path.join(dir, `${run.id}.json`), 'utf8');

    expect(raw.trim().startsWith('{')).toBe(false);
    expect(raw.trim().startsWith('v1.')).toBe(true);
    expect(await store.get(run.id)).toMatchObject({ id: run.id, mode: 'research' });
  });

  it('migrates legacy plaintext operator run files to encrypted storage', async () => {
    const dir = await createTempDir();
    const store = new FileOperatorRunStore(dir);
    const run = buildOperatorRun({
      source: 'cli',
      text: 'research local-first agents with sources',
      mode: 'research',
    });

    await mkdir(dir, { recursive: true });
    await writeFile(path.join(dir, `${run.id}.json`), `${JSON.stringify(run, null, 2)}\n`, 'utf8');

    const loaded = await store.get(run.id);
    const migratedRaw = await readFile(path.join(dir, `${run.id}.json`), 'utf8');

    expect(loaded).toMatchObject({ id: run.id, mode: 'research' });
    expect(migratedRaw.trim().startsWith('v1.')).toBe(true);
  });

  it('resolves approvals without executing local side effects', async () => {
    const dir = await createTempDir();
    const store = new FileOperatorRunStore(dir);
    const run = await store.create({
      source: 'cli',
      text: 'implement a repository patch',
      mode: 'code',
    });
    const approvalId = run.approvals[0]?.id;

    expect(approvalId).toBeDefined();
    expect(await listOperatorApprovals(store)).toHaveLength(1);

    const approval = await resolveOperatorApproval(approvalId!, 'approved', 'test-user', store);
    const updated = await store.get(run.id);

    expect(approval?.status).toBe('approved');
    expect(updated?.status).toBe('planned');
    expect(updated?.reasoning.depth).toBe('deep');
    expect(updated?.steps.find((step) => step.approvalId === approvalId)?.status).toBe('pending');
    expect(updated?.notes.at(-1)).toContain('approved');
    expect(updated?.continuity.openItemCount).toBeGreaterThan(0);
  });

  it('keeps code runs blocked until verification evidence is recorded', async () => {
    const dir = await createTempDir();
    const store = new FileOperatorRunStore(dir);
    const run = await store.create({
      source: 'cli',
      text: 'implement a repository patch',
      mode: 'code',
    });
    const approvalId = run.approvals[0]?.id;

    await resolveOperatorApproval(approvalId!, 'approved', 'test-user', store);
    const updated = await recordOperatorRunArtifact(
      run.id,
      {
        kind: 'summary',
        title: 'Code summary',
        content: 'Plan only; no checks have run.',
      },
      store
    );

    expect(updated?.status).toBe('blocked');
    expect(updated?.verification.status).toBe('blocked');
    expect(updated?.verification.summary).toContain('quality gate');
  });

  it('records inspectable artifacts and verification state for completed runs', async () => {
    const dir = await createTempDir();
    const store = new FileOperatorRunStore(dir);
    const run = await store.create({
      source: 'cli',
      text: 'research local-first operator runtimes with sources',
      mode: 'research',
    });

    const updated = await recordOperatorRunArtifact(
      run.id,
      {
        kind: 'research',
        title: 'Research result',
        content: 'Answer:\nGrounded result.\n\nSources:\n[1] Example - https://example.com',
        metadata: {
          sourceCount: 1,
        },
      },
      store
    );

    expect(updated?.status).toBe('completed');
    expect(updated?.verification.status).toBe('passed');
    expect(updated?.qualityGates.every((gate) => gate.status === 'passed')).toBe(true);
    expect(updated?.artifacts.at(-1)?.title).toBe('Research result');
    expect(updated?.artifacts.at(-1)?.metadata.sourceCount).toBe(1);
  });

  it('allows code runs to complete after repository inspection and verification evidence are recorded', async () => {
    const dir = await createTempDir();
    const store = new FileOperatorRunStore(dir);
    const run = await store.create({
      source: 'cli',
      text: 'implement a repository patch',
      mode: 'code',
    });
    const approvalId = run.approvals[0]?.id;

    await resolveOperatorApproval(approvalId!, 'approved', 'test-user', store);
    const updated = await recordOperatorRunArtifact(
      run.id,
      {
        kind: 'summary',
        title: 'Code verification',
        content: 'Repository inspected. Focused checks passed.',
        metadata: {
          repoInspected: true,
          checksPassed: true,
        },
      },
      store
    );

    expect(updated?.status).toBe('completed');
    expect(updated?.verification.status).toBe('passed');
    expect(updated?.qualityGates.every((gate) => gate.status === 'passed')).toBe(true);
    expect(updated?.artifacts.at(-1)?.metadata).toMatchObject({
      repoInspected: true,
      checksPassed: true,
    });
  });

  it('fails research verification when no sources or unavailable state are recorded', async () => {
    const dir = await createTempDir();
    const store = new FileOperatorRunStore(dir);
    const run = await store.create({
      source: 'cli',
      text: 'research local-first operator runtimes with sources',
      mode: 'research',
    });

    const updated = await recordOperatorRunArtifact(
      run.id,
      {
        kind: 'research',
        title: 'Unsourced result',
        content: 'Answer without citation markers.',
      },
      store
    );

    expect(updated?.status).toBe('failed');
    expect(updated?.verification.status).toBe('failed');
    expect(updated?.qualityGates.map((gate) => gate.status)).toEqual(['failed', 'failed']);
  });

  it('allows honest research fallback when live evidence is unavailable', async () => {
    const dir = await createTempDir();
    const store = new FileOperatorRunStore(dir);
    const run = await store.create({
      source: 'cli',
      text: 'research unavailable source path',
      mode: 'research',
    });

    const updated = await recordOperatorRunArtifact(
      run.id,
      {
        kind: 'research',
        title: 'Unavailable result',
        content: 'Live evidence is unavailable for this run.',
        metadata: {
          unavailable: true,
        },
      },
      store
    );

    expect(updated?.status).toBe('completed');
    expect(updated?.verification.status).toBe('passed');
    expect(updated?.qualityGates.every((gate) => gate.status === 'passed')).toBe(true);
  });
});
