import { mkdir, mkdtemp, rm } from 'fs/promises';
import os from 'os';
import path from 'path';
import { describe, expect, it, afterEach } from 'vitest';
import { executeBoundedTerminalCommand } from '@/core/dispatch/runtime/terminal-runtime';

describe('bounded terminal runtime', () => {
  let tmpDir = '';

  afterEach(async () => {
    if (tmpDir) {
      await rm(tmpDir, { recursive: true, force: true });
      tmpDir = '';
    }
  });

  it('fails closed when cwd escapes the task workspace', async () => {
    tmpDir = await mkdtemp(path.join(os.tmpdir(), 'elyan-terminal-'));
    const workspacePath = path.join(tmpDir, 'tasks', 'dispatch_terminal');
    await mkdir(workspacePath, { recursive: true });

    await expect(
      executeBoundedTerminalCommand({
        cwd: tmpDir,
        command: process.execPath,
        args: ['--version'],
        timeoutMs: 1000,
        runtime: {
          taskId: 'dispatch_terminal',
          workspacePath,
          tracePath: path.join(workspacePath, 'traces', 'runtime-trace.jsonl'),
          recoveryState: 'fresh',
        },
      })
    ).rejects.toThrow(/escapes the task workspace/);
  });
});
