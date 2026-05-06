#!/usr/bin/env node
/* eslint-disable @typescript-eslint/no-require-imports */

const { execFileSync } = require('child_process');
const fs = require('fs');
const path = require('path');

const ROOT = path.resolve(__dirname, '..');

const FORBIDDEN_PATHS = new Set([
  '.env',
  '.env.local',
  '.env.production',
  '.env.prod',
  'vps.md',
  'VPS.md',
  'server.md',
  'secrets.md',
  'credentials.md',
]);

const FORBIDDEN_PATH_PATTERNS = [
  /^\.ssh\//,
  /^ssh\//,
  /(^|\/)id_(rsa|ed25519|ecdsa)(\.pub)?$/,
  /\.(pem|key|p12|pfx)$/i,
];

const ALLOWED_EXAMPLE_FILES = new Set([
  '.env.example',
  'release/systemd/elyan.env.example',
]);

const SECRET_ASSIGNMENT_RE =
  /\b(password|passwd|secret|token|api[_-]?key|private[_-]?key)\b\s*[:=]\s*["']?([^"'\s#]+)/i;
const KNOWN_SECRET_VALUE_RE =
  /\b(ghp_[A-Za-z0-9_]{20,}|github_pat_[A-Za-z0-9_]{20,}|sk-[A-Za-z0-9_-]{20,}|xox[baprs]-[A-Za-z0-9-]{20,}|AKIA[0-9A-Z]{16})\b/;

const SAFE_PLACEHOLDERS = new Set([
  '',
  'change-me',
  'changeme',
  'example',
  'example-token',
  'placeholder',
  'replace-me',
  'your-token',
  'your-secret',
  'your-api-key',
  '<redacted>',
  '[redacted]',
]);

function gitLsFiles() {
  const output = execFileSync('git', ['ls-files', '-z'], {
    cwd: ROOT,
    encoding: 'utf8',
  });

  return output.split('\0').filter(Boolean);
}

function isForbiddenPath(filePath) {
  if (FORBIDDEN_PATHS.has(filePath)) {
    return true;
  }

  return FORBIDDEN_PATH_PATTERNS.some((pattern) => pattern.test(filePath));
}

function normalizeSecretValue(value) {
  return String(value || '').trim().replace(/^["']|["']$/g, '');
}

function isSafePlaceholder(value) {
  const normalized = normalizeSecretValue(value).toLowerCase();
  return SAFE_PLACEHOLDERS.has(normalized) || normalized.startsWith('http://127.0.0.1') || normalized.startsWith('http://localhost');
}

function scanTextFile(filePath) {
  if (ALLOWED_EXAMPLE_FILES.has(filePath)) {
    return [];
  }

  const absolutePath = path.join(ROOT, filePath);
  if (!fs.existsSync(absolutePath)) {
    return [];
  }

  const stat = fs.statSync(absolutePath);
  if (stat.size > 1024 * 1024) {
    return [];
  }

  const content = fs.readFileSync(absolutePath, 'utf8');
  const findings = [];

  if (/-----BEGIN (RSA |OPENSSH |EC |DSA |PGP )?PRIVATE KEY-----/.test(content)) {
    findings.push(`${filePath}: contains a private key block`);
  }

  if (KNOWN_SECRET_VALUE_RE.test(content)) {
    findings.push(`${filePath}: contains a known secret token pattern`);
  }

  const extension = path.extname(filePath).toLowerCase();
  const shouldScanAssignments =
    ALLOWED_EXAMPLE_FILES.has(filePath) ||
    ['.env', '.md', '.txt', '.yml', '.yaml', '.json', '.toml', '.ini', '.conf', '.service'].includes(extension) ||
    path.basename(filePath).toLowerCase().includes('config') ||
    path.basename(filePath).toLowerCase().includes('secret') ||
    filePath === '.npmrc';

  if (!shouldScanAssignments) {
    return findings;
  }

  content.split(/\r?\n/).forEach((line, index) => {
    const match = line.match(SECRET_ASSIGNMENT_RE);
    if (!match) {
      return;
    }

    const value = normalizeSecretValue(match[2]);
    if (isSafePlaceholder(value)) {
      return;
    }

    findings.push(`${filePath}:${index + 1}: contains a non-placeholder secret-like assignment`);
  });

  return findings;
}

function main() {
  const trackedFiles = gitLsFiles();
  const findings = [];

  for (const filePath of trackedFiles) {
    const absolutePath = path.join(ROOT, filePath);

    if (!fs.existsSync(absolutePath)) {
      continue;
    }

    if (isForbiddenPath(filePath)) {
      findings.push(`${filePath}: forbidden sensitive operations file is present in the working tree`);
      continue;
    }

    findings.push(...scanTextFile(filePath));
  }

  if (findings.length > 0) {
    console.error('Security check failed. Do not commit or release sensitive operational material.');
    for (const finding of findings) {
      console.error(`- ${finding}`);
    }
    process.exit(1);
  }

  console.log('Security check passed.');
}

if (require.main === module) {
  main();
}

module.exports = {
  isForbiddenPath,
  scanTextFile,
};
