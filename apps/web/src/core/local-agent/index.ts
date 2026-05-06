import { mkdir, readdir, readFile, rename, writeFile } from 'fs/promises';
import path from 'path';
import { readRuntimeSettingsSync } from '@/core/runtime-settings';
import { createLocalAgentRunId, writeLocalAgentEvidence } from './evidence';
import { evaluateLocalAgentAction } from './policy';
import { localAgentActionSchema, type LocalAgentAction, type LocalAgentExecutionResult } from './types';
import type { CapabilityExecutionContext } from '@/core/capabilities/types';
import { executeBoundedTerminalCommand } from '@/core/dispatch/runtime/terminal-runtime';

export * from './types';
export * from './policy';
export * from './evidence';

function resolveActionPath(inputPath: string, workspacePath?: string) {
  if (path.isAbsolute(inputPath)) {
    return path.resolve(inputPath);
  }

  const basePath = workspacePath ? path.resolve(workspacePath) : process.cwd();
  return path.resolve(basePath, inputPath);
}

async function atomicWriteText(filePath: string, content: string) {
  await mkdir(path.dirname(filePath), { recursive: true });
  const tempPath = `${filePath}.${process.pid}.${Date.now()}.tmp`;
  await writeFile(tempPath, content, 'utf8');
  await rename(tempPath, filePath);
}

async function executeAllowedAction(action: LocalAgentAction, runtime?: CapabilityExecutionContext['runtime'], signal?: AbortSignal) {
  switch (action.type) {
    case 'filesystem.list': {
      const entries = await readdir(resolveActionPath(action.path, runtime?.workspacePath), { withFileTypes: true });
      return entries.map((entry) => ({ name: entry.name, type: entry.isDirectory() ? 'directory' : entry.isFile() ? 'file' : 'other' }));
    }
    case 'filesystem.read_text':
      return { content: await readFile(resolveActionPath(action.path, runtime?.workspacePath), 'utf8') };
    case 'filesystem.write_text':
    case 'filesystem.patch_text':
      await atomicWriteText(resolveActionPath(action.path, runtime?.workspacePath), action.content);
      return { written: true };
    case 'filesystem.move':
    case 'filesystem.restore':
      await mkdir(path.dirname(resolveActionPath(action.targetPath, runtime?.workspacePath)), { recursive: true });
      await rename(
        resolveActionPath(action.path, runtime?.workspacePath),
        resolveActionPath(action.targetPath, runtime?.workspacePath)
      );
      return { moved: true, targetPath: resolveActionPath(action.targetPath, runtime?.workspacePath) };
    case 'filesystem.trash': {
      const source = resolveActionPath(action.path, runtime?.workspacePath);
      const trashDir = runtime?.workspacePath
        ? path.join(runtime.workspacePath, '.trash')
        : path.resolve(process.cwd(), 'storage', 'trash');
      await mkdir(trashDir, { recursive: true });
      const targetPath = path.join(trashDir, `${Date.now()}-${path.basename(source)}`);
      await rename(source, targetPath);
      return { trashed: true, targetPath };
    }
    case 'terminal.exec': {
      const result = await executeBoundedTerminalCommand({
        cwd: resolveActionPath(action.cwd, runtime?.workspacePath),
        command: action.command,
        args: action.args,
        timeoutMs: action.timeoutMs,
        interactive: action.interactive ?? false,
        runtime,
        signal,
      });
      return {
        stdout: result.stdout,
        stderr: result.stderr,
        exitCode: result.exitCode,
        commandLine: result.commandLine,
      };
    }
  }
}

export async function executeLocalAgentAction(
  input: unknown,
  options?: { runtime?: CapabilityExecutionContext['runtime']; signal?: AbortSignal }
): Promise<LocalAgentExecutionResult> {
  const action = localAgentActionSchema.parse(input);
  const settings = readRuntimeSettingsSync();
  const runId = action.runId ?? createLocalAgentRunId();
  const decision = evaluateLocalAgentAction(action, settings.localAgent, options?.runtime);

  if (!decision.allowed) {
    await writeLocalAgentEvidence({
      runId,
      evidenceDir: settings.localAgent.evidenceDir,
      action,
      decision,
      phase: 'rejected',
      error: decision.reason,
    });
    return {
      ok: false,
      actionType: action.type,
      runId,
      decision,
      error: decision.reason,
    };
  }

  await writeLocalAgentEvidence({
    runId,
    evidenceDir: settings.localAgent.evidenceDir,
    action,
    decision,
    phase: 'started',
  });

  try {
    const output = await executeAllowedAction(action, options?.runtime, options?.signal);
    await writeLocalAgentEvidence({
      runId,
      evidenceDir: settings.localAgent.evidenceDir,
      action,
      decision,
      phase: 'completed',
      output,
    });
    return {
      ok: true,
      actionType: action.type,
      runId,
      decision,
      output,
    };
  } catch (error) {
    const message = error instanceof Error ? error.message : 'local operator action failed';
    await writeLocalAgentEvidence({
      runId,
      evidenceDir: settings.localAgent.evidenceDir,
      action,
      decision,
      phase: 'failed',
      error: message,
    });
    return {
      ok: false,
      actionType: action.type,
      runId,
      decision,
      error: message,
    };
  }
}

export function readLocalAgentStatus() {
  const settings = readRuntimeSettingsSync();
  return {
    enabled: settings.localAgent.enabled,
    allowedRoots: settings.localAgent.allowedRoots,
    protectedPathCount: settings.localAgent.protectedPaths.length,
    evidenceDir: settings.localAgent.evidenceDir,
    approvalPolicy: settings.localAgent.approvalPolicy,
  };
}
