import { mkdir, writeFile } from 'node:fs/promises';
import os from 'node:os';
import path from 'node:path';
import { beforeEach, afterEach, describe, expect, it, vi } from 'vitest';
import { buildWorkspaceStatusSnapshot } from '@/core/workspace';
import { readRuntimeSettingsSync } from '@/core/runtime-settings';

describe('workspace status snapshot', () => {
  const originalEnv = {
    GITHUB_REPO: process.env.GITHUB_REPO,
    GITHUB_TOKEN: process.env.GITHUB_TOKEN,
    OBSIDIAN_VAULT_PATH: process.env.OBSIDIAN_VAULT_PATH,
  };

  beforeEach(() => {
    process.env.GITHUB_REPO = 'elyan-dev/elyan';
    process.env.GITHUB_TOKEN = 'token';
    process.env.ELYAN_ALLOW_GITHUB_WORKSPACE_FETCH_IN_TESTS = '1';
  });

  afterEach(() => {
    process.env.GITHUB_REPO = originalEnv.GITHUB_REPO;
    process.env.GITHUB_TOKEN = originalEnv.GITHUB_TOKEN;
    process.env.OBSIDIAN_VAULT_PATH = originalEnv.OBSIDIAN_VAULT_PATH;
    delete process.env.ELYAN_ALLOW_GITHUB_WORKSPACE_FETCH_IN_TESTS;
    vi.unstubAllGlobals();
  });

  it('surfaces GitHub and Obsidian context when configured', async () => {
    const vaultPath = await mkTempVault();
    process.env.OBSIDIAN_VAULT_PATH = vaultPath;

    await mkdir(path.join(vaultPath, 'Daily'), { recursive: true });
    await writeFile(
      path.join(vaultPath, 'Daily', 'brief.md'),
      ['# Workspace brief', 'Remember to review the release stream.', 'GitHub updates first.'].join('\n'),
      'utf8'
    );

    vi.stubGlobal(
      'fetch',
      vi.fn(async () => ({
        ok: true,
        json: async () => ({
          full_name: 'elyan-dev/elyan',
          description: 'Local-first operator runtime',
          updated_at: '2026-04-24T10:00:00.000Z',
          open_issues_count: 3,
        }),
      }))
    );

    const snapshot = await buildWorkspaceStatusSnapshot(readRuntimeSettingsSync());

    expect(snapshot.ready).toBe(true);
    expect(snapshot.summary.connectedSourceCount).toBeGreaterThanOrEqual(2);
    expect(snapshot.sources.find((source) => source.kind === 'github')?.state).toBe('connected');
    expect(snapshot.sources.find((source) => source.kind === 'obsidian')?.state).toBe('connected');
    expect(snapshot.brief.some((entry) => entry.kind === 'note')).toBe(true);
    expect(snapshot.jobs.find((job) => job.id === 'morning_brief')?.enabled).toBe(true);
  });
});

async function mkTempVault() {
  const root = path.join(os.tmpdir(), `elyan-vault-${Date.now()}-${Math.random().toString(16).slice(2)}`);
  await mkdir(root, { recursive: true });
  return root;
}
