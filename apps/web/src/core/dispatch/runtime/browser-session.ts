import { access } from 'fs/promises';
import path from 'path';
import type { BrowserContext } from 'playwright';
import type { CapabilityRuntimeContext } from '@/core/capabilities/types';
import { isPathInsideWorkspace } from './workspace';

async function fileExists(filePath: string) {
  try {
    await access(filePath);
    return true;
  } catch {
    return false;
  }
}

export function resolveTaskBrowserSessionPath(runtime?: CapabilityRuntimeContext) {
  if (runtime?.browserSessionPath && (!runtime.workspacePath || isPathInsideWorkspace(runtime.browserSessionPath, runtime.workspacePath))) {
    return runtime.browserSessionPath;
  }

  if (runtime?.workspacePath) {
    return path.join(runtime.workspacePath, 'browser', 'storage-state.json');
  }

  return undefined;
}

export function resolveWorkspaceBrowserSessionPath(runtime?: CapabilityRuntimeContext) {
  return resolveTaskBrowserSessionPath(runtime);
}

export async function loadBrowserStorageState(runtime?: CapabilityRuntimeContext) {
  const sessionPath = resolveWorkspaceBrowserSessionPath(runtime);
  if (!sessionPath) {
    return undefined;
  }

  return (await fileExists(sessionPath)) ? sessionPath : undefined;
}

export async function persistBrowserStorageState(context: BrowserContext, runtime?: CapabilityRuntimeContext) {
  const sessionPath = resolveWorkspaceBrowserSessionPath(runtime);
  if (!sessionPath) {
    return;
  }

  await context.storageState({ path: sessionPath });
}
