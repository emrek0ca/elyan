import { execFile } from 'node:child_process';
import fs from 'node:fs/promises';
import path from 'node:path';
import type { DesktopPlatform, NativeDesktopProcessInfo, NativeDesktopSnapshot } from '../../shared/protocol';
import type { NativeWindowAddon } from './addon-loader';

function execFileAsync(file: string, args: string[], timeoutMs: number): Promise<string> {
  return new Promise((resolve, reject) => {
    execFile(file, args, { timeout: timeoutMs, windowsHide: true }, (error, stdout) => {
      if (error) {
        reject(error);
        return;
      }
      resolve(String(stdout ?? ''));
    });
  });
}

function dedupeProcesses(items: NativeDesktopProcessInfo[]): NativeDesktopProcessInfo[] {
  const seen = new Set<number>();
  const deduped: NativeDesktopProcessInfo[] = [];
  for (const item of items) {
    if (!Number.isInteger(item.pid) || item.pid <= 0 || seen.has(item.pid)) {
      continue;
    }
    seen.add(item.pid);
    deduped.push(item);
  }
  return deduped.slice(0, 128);
}

function withFrontmostProcess(
  items: NativeDesktopProcessInfo[],
  activeWindow: NativeDesktopSnapshot['activeWindow'],
): NativeDesktopProcessInfo[] {
  if (!activeWindow.available || !Number.isInteger(activeWindow.processId) || (activeWindow.processId ?? 0) <= 0) {
    return items;
  }
  const activePid = Number(activeWindow.processId);
  const next = items.map((item) =>
    item.pid === activePid
      ? {
          ...item,
          frontmost: true,
          executablePath: activeWindow.executablePath || item.executablePath,
          bundleId: activeWindow.bundleId || item.bundleId,
        }
      : { ...item, frontmost: item.frontmost === true },
  );
  if (next.some((item) => item.pid === activePid)) {
    next.sort((left, right) => Number(Boolean(right.frontmost)) - Number(Boolean(left.frontmost)));
    return next;
  }
  const appName = String(activeWindow.appName ?? '').trim();
  if (!appName) {
    return next;
  }
  return [
    {
      pid: activePid,
      name: appName,
      executablePath: String(activeWindow.executablePath ?? '').trim() || undefined,
      bundleId: String(activeWindow.bundleId ?? '').trim() || undefined,
      frontmost: true,
    },
    ...next,
  ].slice(0, 128);
}

function parseUnixProcesses(output: string): NativeDesktopProcessInfo[] {
  const parsed: NativeDesktopProcessInfo[] = [];
  for (const rawLine of output.split('\n')) {
    const line = rawLine.trim();
    if (!line) {
      continue;
    }
    const match = line.match(/^(\d+)\s+(.+)$/);
    if (!match) {
      continue;
    }
    const pid = Number.parseInt(match[1] ?? '', 10);
    const executablePath = String(match[2] ?? '').trim();
    const name = path.basename(executablePath).trim() || executablePath;
    parsed.push({ pid, name, executablePath });
  }
  return dedupeProcesses(parsed);
}

function parseWindowsProcesses(output: string): NativeDesktopProcessInfo[] {
  const parsed: NativeDesktopProcessInfo[] = [];
  for (const rawLine of output.split('\n')) {
    const line = rawLine.trim();
    if (!line) {
      continue;
    }
    const columns = line
      .split('","')
      .map((entry) => entry.replace(/^"/, '').replace(/"$/, '').trim());
    if (columns.length < 2) {
      continue;
    }
    const name = columns[0] ?? '';
    const pid = Number.parseInt(columns[1] ?? '', 10);
    if (!name || !Number.isFinite(pid)) {
      continue;
    }
    parsed.push({ pid, name });
  }
  return dedupeProcesses(parsed);
}

async function collectProcesses(platform: DesktopPlatform): Promise<NativeDesktopProcessInfo[]> {
  if (platform === 'win32') {
    const stdout = await execFileAsync('tasklist', ['/fo', 'csv', '/nh'], 1200);
    return parseWindowsProcesses(stdout);
  }
  const stdout = await execFileAsync('/bin/ps', ['-axo', 'pid=,comm='], 1200);
  return parseUnixProcesses(stdout);
}

export async function buildNativeDesktopSnapshot(
  platform: DesktopPlatform,
  addon: NativeWindowAddon,
): Promise<NativeDesktopSnapshot> {
  const base: NativeDesktopSnapshot = {
    ...addon.runtimeSnapshot,
    collectedAt: new Date().toISOString(),
  };

  if (!base.processInspectionAvailable) {
    return base;
  }

  try {
    const items = withFrontmostProcess(await collectProcesses(platform), base.activeWindow);
    return {
      ...base,
      processes: {
        available: true,
        total: items.length,
        items,
      },
      lastErrorCode: '',
    };
  } catch {
    return {
      ...base,
      processes: {
        available: false,
        total: 0,
        items: [],
      },
      lastErrorCode: 'process_snapshot_failed',
    };
  }
}

export async function persistNativeDesktopSnapshot(snapshot: NativeDesktopSnapshot, targetPath: string): Promise<void> {
  const payload = JSON.stringify(snapshot, null, 2);
  await fs.mkdir(path.dirname(targetPath), { recursive: true });
  await fs.writeFile(targetPath, payload, 'utf-8');
}
