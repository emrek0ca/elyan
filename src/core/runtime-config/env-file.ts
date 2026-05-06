import { existsSync, mkdirSync, readFileSync, writeFileSync } from 'fs';
import { parse } from 'dotenv';
import { getGlobalEnvPath as resolveGlobalEnvPath, resolveGlobalConfigDir } from '@/lib/runtime-paths';

const globalConfigDir = resolveGlobalConfigDir();
const globalEnvPath = resolveGlobalEnvPath();

function ensureGlobalConfigDir() {
  if (!existsSync(globalConfigDir)) {
    mkdirSync(globalConfigDir, { recursive: true });
  }
}

function escapeRegex(value: string) {
  return value.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
}

export function getGlobalEnvPath() {
  return globalEnvPath;
}

export function readRuntimeEnvFile() {
  if (!existsSync(globalEnvPath)) {
    return {};
  }

  return parse(readFileSync(globalEnvPath, 'utf8'));
}

export function readRuntimeEnvValue(key: string) {
  return readRuntimeEnvFile()[key] ?? process.env[key];
}

export function readMergedRuntimeEnv() {
  return {
    ...process.env,
    ...readRuntimeEnvFile(),
  };
}

export function setRuntimeEnvValue(key: string, value: string) {
  ensureGlobalConfigDir();
  const current = existsSync(globalEnvPath) ? readFileSync(globalEnvPath, 'utf8') : '';
  const regex = new RegExp(`^${escapeRegex(key)}=.*$`, 'm');
  const nextLine = `${key}=${value}`;
  const next = regex.test(current) ? current.replace(regex, nextLine) : `${current.trim()}\n${nextLine}`;
  writeFileSync(globalEnvPath, `${next.trim()}\n`, 'utf8');
}

export function removeRuntimeEnvValue(key: string) {
  if (!existsSync(globalEnvPath)) {
    return;
  }

  const current = readFileSync(globalEnvPath, 'utf8');
  const regex = new RegExp(`^${escapeRegex(key)}=.*$\n?`, 'gm');
  const next = current.replace(regex, '').trim();
  writeFileSync(globalEnvPath, next ? `${next}\n` : '', 'utf8');
}
