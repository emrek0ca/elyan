import { mkdir } from 'fs/promises';
import path from 'path';
import { execa } from 'execa';
import { spawn } from 'node-pty';
import type { CapabilityRuntimeContext } from '@/core/capabilities/types';
import { appendJsonLine, isPathInsideWorkspace } from './workspace';

export type BoundedTerminalCommandInput = {
  cwd: string;
  command: string;
  args: string[];
  timeoutMs: number;
  interactive?: boolean;
  runtime?: CapabilityRuntimeContext;
  signal?: AbortSignal;
};

export type BoundedTerminalCommandOutput = {
  stdout: string;
  stderr: string;
  exitCode: number;
  commandLine: string;
  interactive: boolean;
};

const MAX_STREAMED_OUTPUT_CHARS = 200_000;

async function appendTerminalTrace(runtime: CapabilityRuntimeContext | undefined, note: string, data?: Record<string, unknown>) {
  if (!runtime?.tracePath) {
    return;
  }

  await appendJsonLine(runtime.tracePath, {
    timestamp: new Date().toISOString(),
    kind: 'lifecycle',
    taskId: runtime.taskId ?? 'unknown',
    status: 'running',
    note,
    data: {
      scope: 'terminal',
      ...(data ?? {}),
    },
  }).catch(() => undefined);
}

function mergeSignals(signal?: AbortSignal) {
  const controller = new AbortController();

  if (signal?.aborted) {
    controller.abort();
  } else if (signal) {
    signal.addEventListener('abort', () => controller.abort(), { once: true });
  }

  return controller;
}

async function executeWithExeca(input: BoundedTerminalCommandInput): Promise<BoundedTerminalCommandOutput> {
  await appendTerminalTrace(input.runtime, `Executing terminal command: ${input.command}`, {
    cwd: input.cwd,
    interactive: false,
  });
  const result = await execa(input.command, input.args, {
    cwd: input.cwd,
    timeout: input.timeoutMs,
    reject: false,
    shell: false,
    all: true,
    signal: input.signal,
    env: process.env as Record<string, string>,
    cleanup: true,
    killSignal: 'SIGTERM',
    forceKillAfterDelay: 1_500,
    maxBuffer: MAX_STREAMED_OUTPUT_CHARS,
  });

  const stdout = (result.stdout ?? '').slice(0, MAX_STREAMED_OUTPUT_CHARS);
  const stderr = (result.stderr ?? '').slice(0, MAX_STREAMED_OUTPUT_CHARS);
  await appendTerminalTrace(input.runtime, `Terminal command completed: ${input.command}`, {
    cwd: input.cwd,
    exitCode: result.exitCode ?? 0,
    interactive: false,
  });

  return {
    stdout,
    stderr,
    exitCode: result.exitCode ?? 0,
    commandLine: [input.command, ...input.args].join(' ').trim(),
    interactive: false,
  };
}

async function executeWithPty(input: BoundedTerminalCommandInput): Promise<BoundedTerminalCommandOutput> {
  const sessionDir = input.runtime?.terminalSessionPath
    ? path.dirname(input.runtime.terminalSessionPath)
    : path.join(input.cwd, '.elyan-terminal');
  await mkdir(sessionDir, { recursive: true });

  return await new Promise<BoundedTerminalCommandOutput>((resolve, reject) => {
    const shell = process.env.SHELL || '/bin/zsh';
    const pty = spawn(input.command || shell, input.command ? input.args : [], {
      name: 'xterm-color',
      cols: 120,
      rows: 30,
      cwd: input.cwd,
      env: process.env as Record<string, string>,
    });
    const controller = mergeSignals(input.signal);
    let stdout = '';
    const stderr = '';
    let finished = false;
    let truncated = false;

    void appendTerminalTrace(input.runtime, `Starting interactive terminal command: ${input.command}`, {
      cwd: input.cwd,
      interactive: true,
    });

    const cleanup = (error?: unknown) => {
      if (finished) {
        return;
      }

      finished = true;
      try {
        pty.kill('SIGKILL');
      } catch {
        // ignore
      }

      clearTimeout(timeout);
      controller.signal.removeEventListener('abort', onAbort);
      if (error) {
        reject(error instanceof Error ? error : new Error(String(error)));
      }
    };

    const onAbort = () => {
      cleanup(new Error('Terminal command aborted.'));
    };

    controller.signal.addEventListener('abort', onAbort, { once: true });

    const timeout = setTimeout(() => {
      cleanup(new Error(`Terminal command timed out after ${input.timeoutMs}ms.`));
    }, input.timeoutMs);

    pty.onData((chunk) => {
      if (truncated) {
        return;
      }

      stdout += chunk;
      if (stdout.length > MAX_STREAMED_OUTPUT_CHARS) {
        truncated = true;
        stdout = stdout.slice(0, MAX_STREAMED_OUTPUT_CHARS);
        cleanup(new Error(`Terminal command output exceeded ${MAX_STREAMED_OUTPUT_CHARS} characters.`));
      }
    });

    pty.onExit(({ exitCode }) => {
      if (finished) {
        return;
      }

      finished = true;
      clearTimeout(timeout);
      controller.signal.removeEventListener('abort', onAbort);
      void appendTerminalTrace(input.runtime, `Terminal command completed: ${input.command}`, {
        cwd: input.cwd,
        exitCode,
        interactive: true,
      });
      resolve({
        stdout: stdout.slice(0, MAX_STREAMED_OUTPUT_CHARS),
        stderr,
        exitCode,
        commandLine: [input.command, ...input.args].join(' ').trim(),
        interactive: true,
      });
    });
  });
}

export async function executeBoundedTerminalCommand(input: BoundedTerminalCommandInput) {
  if (input.runtime?.workspacePath && !isPathInsideWorkspace(input.cwd, input.runtime.workspacePath)) {
    await appendTerminalTrace(input.runtime, 'Blocked terminal command outside task workspace.', {
      cwd: input.cwd,
      workspacePath: input.runtime.workspacePath,
    });
    throw new Error(`Terminal cwd escapes the task workspace: ${input.cwd}`);
  }

  if (input.interactive) {
    return executeWithPty(input);
  }

  return executeWithExeca(input);
}
