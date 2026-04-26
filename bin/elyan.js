#!/usr/bin/env node

const { program } = require('commander');
const chalk = require('chalk');
const { spawn, spawnSync } = require('child_process');
const fs = require('fs');
const os = require('os');
const path = require('path');
const { getGlobalEnvPath, resolveGlobalConfigDir } = require(path.join(__dirname, '..', 'src', 'lib', 'runtime-paths.js'));
const {
  collectSetCookieHeaders,
  cookiesFromSetCookieHeaders,
  createCliSessionStore,
  getCliBaseUrl,
  mergeCookieHeader,
} = require('./lib/cli-session');
const {
  commandExists,
  isHomebrewInstall,
  isSourceCheckout,
  runCommand,
} = require('./lib/system');
const {
  buildMcpDoctor,
  disableMcpTool,
  setMcpServerEnabled,
  setMcpServers,
} = require('./lib/mcp-settings');
const packageJson = require(path.join(__dirname, '..', 'package.json'));

program
  .name('elyan')
  .description('Elyan - local-first personal agent runtime with hosted access and controlled operator routing.')
  .showHelpAfterError(true)
  .version(packageJson.version);

// Paths defaults
const GLOBAL_DIR = resolveGlobalConfigDir();
const GLOBAL_ENV = getGlobalEnvPath();
const CLI_SESSION_PATH = path.join(GLOBAL_DIR, 'control-plane-session.json');
const {
  readCliSession,
  writeCliSession,
  clearCliSession,
} = createCliSessionStore(CLI_SESSION_PATH);

/**
 * Ensures global config directory exists
 */
function ensureGlobalConfigDir() {
  if (!fs.existsSync(GLOBAL_DIR)) {
    fs.mkdirSync(GLOBAL_DIR, { recursive: true });
  }
}

/**
 * Loads .env safely ensuring we don't crash
 */
function loadEnvSafe() {
  require('dotenv').config(); 
  if (fs.existsSync(GLOBAL_ENV)) {
    require('dotenv').config({ path: GLOBAL_ENV, override: true });
  }
}

const LOCAL_RUNTIME_SETTINGS = path.join(process.cwd(), 'storage', 'runtime', 'settings.json');
const DEFAULT_STORAGE_DIR = 'storage';
const RECOMMENDED_LOCAL_MODEL = 'llama3.2';
const LAUNCHD_LABEL = 'dev.elyan.local-runtime';

function createDefaultRuntimeSettings() {
  return {
    version: 1,
    routing: {
      preferredModelId: undefined,
      routingMode: 'local_first',
      searchEnabled: true,
    },
    channels: {
      telegram: {
        enabled: false,
        mode: 'polling',
        webhookPath: '/api/channels/telegram/webhook',
        allowedChatIds: [],
      },
      whatsappCloud: {
        enabled: false,
        webhookPath: '/api/channels/whatsapp/webhook',
      },
      whatsappBaileys: {
        enabled: false,
        sessionPath: 'storage/channels/whatsapp-baileys.json',
      },
      imessage: {
        enabled: false,
        mode: 'bluebubbles',
        webhookPath: '/api/channels/imessage/bluebubbles/webhook',
      },
    },
    voice: {
      enabled: false,
      wakeWord: 'elyan',
      language: 'en',
      sampleRate: 16000,
    },
    team: {
      enabled: true,
      defaultMode: 'auto',
      maxConcurrentAgents: 2,
      maxTasksPerRun: 6,
      allowCloudEscalation: false,
    },
    localAgent: {
      enabled: false,
      allowedRoots: ['.'],
      protectedPaths: [
        '.env',
        '.ssh',
        '.gnupg',
        '.aws',
        '.config/gcloud',
        '.kube',
        'id_rsa',
        'id_ed25519',
        'wallet',
        'Library/Keychains',
        '/etc',
        '/System',
        '/private/etc',
      ],
      approvalPolicy: {
        readOnly: 'AUTO',
        writeSafe: 'CONFIRM',
        writeSensitive: 'SCREEN',
        destructive: 'TWO_FA',
        systemCritical: 'TWO_FA',
      },
      evidenceDir: 'storage/evidence',
    },
    mcp: {
      servers: [],
    },
  };
}

function ensureParentDir(filePath) {
  fs.mkdirSync(path.dirname(filePath), { recursive: true });
}

function readRuntimeSettingsFile() {
  const defaults = createDefaultRuntimeSettings();
  if (!fs.existsSync(LOCAL_RUNTIME_SETTINGS)) {
    ensureParentDir(LOCAL_RUNTIME_SETTINGS);
    atomicWriteFileSync(LOCAL_RUNTIME_SETTINGS, `${JSON.stringify(defaults, null, 2)}\n`);
    return defaults;
  }

  try {
    const raw = fs.readFileSync(LOCAL_RUNTIME_SETTINGS, 'utf8');
    return raw.trim() ? deepMerge(defaults, JSON.parse(raw)) : defaults;
  } catch {
    return defaults;
  }
}

function writeRuntimeSettingsFile(settings) {
  ensureParentDir(LOCAL_RUNTIME_SETTINGS);
  atomicWriteFileSync(LOCAL_RUNTIME_SETTINGS, `${JSON.stringify(settings, null, 2)}\n`);
}

function atomicWriteFileSync(filePath, content) {
  ensureParentDir(filePath);
  const tempPath = `${filePath}.${process.pid}.${Date.now()}.tmp`;
  fs.writeFileSync(tempPath, content, 'utf8');
  fs.renameSync(tempPath, filePath);
}

function backupFileIfExists(filePath) {
  if (!fs.existsSync(filePath)) {
    return null;
  }

  const backupPath = `${filePath}.bak.${new Date().toISOString().replace(/[:.]/g, '-')}`;
  fs.copyFileSync(filePath, backupPath);
  return backupPath;
}

function readKeyValueFile(filePath) {
  const result = {};
  if (!fs.existsSync(filePath)) {
    return result;
  }

  for (const line of fs.readFileSync(filePath, 'utf8').split(/\r?\n/)) {
    if (!line || line.trim().startsWith('#') || !line.includes('=')) continue;
    const [key, ...rest] = line.split('=');
    result[key.trim()] = rest.join('=').trim();
  }

  return result;
}

function writeKeyValueFile(filePath, values) {
  const lines = Object.entries(values)
    .filter(([key]) => key)
    .map(([key, value]) => `${key}=${value ?? ''}`);
  atomicWriteFileSync(filePath, `${lines.join('\n')}\n`);
}

function ensureGlobalEnvDefaults(defaults, { backup = false } = {}) {
  ensureGlobalConfigDir();
  const current = readKeyValueFile(GLOBAL_ENV);
  const next = { ...current };
  let changed = false;

  for (const [key, value] of Object.entries(defaults)) {
    if (!next[key]) {
      next[key] = value;
      changed = true;
    }
  }

  if (changed) {
    if (backup) backupFileIfExists(GLOBAL_ENV);
    writeKeyValueFile(GLOBAL_ENV, next);
  }

  return { changed, path: GLOBAL_ENV };
}

function ensureRuntimeStorageDirs(storageDir = DEFAULT_STORAGE_DIR) {
  for (const entry of [
    storageDir,
    path.join(storageDir, 'runtime'),
    path.join(storageDir, 'channels'),
    path.join(storageDir, 'evidence'),
    path.join(storageDir, 'team-runs'),
    path.join(storageDir, 'trash'),
  ]) {
    fs.mkdirSync(path.resolve(process.cwd(), entry), { recursive: true });
  }
}

function getCliSessionCookieHeader() {
  const session = readCliSession();
  return session?.cookieHeader || '';
}

async function fetchAuthedJson(url, timeoutMs = 5000, init = {}) {
  const session = readCliSession();
  const headers = {
    ...(init.headers || {}),
  };

  if (session?.cookieHeader) {
    headers.Cookie = mergeCookieHeader(headers.Cookie || '', session.cookieHeader);
  }

  return fetchJson(url, timeoutMs, {
    ...init,
    headers,
  });
}

async function loginToHostedControlPlane(baseUrl, email, password) {
  const csrfResponse = await fetch(`${baseUrl}/api/auth/csrf`, {
    method: 'GET',
  });
  if (!csrfResponse.ok) {
    throw new Error(`Failed to fetch CSRF token (${csrfResponse.status})`);
  }

  const csrfBody = await csrfResponse.json();
  const csrfCookie = cookiesFromSetCookieHeaders(collectSetCookieHeaders(csrfResponse.headers));
  const response = await fetch(`${baseUrl}/api/auth/callback/credentials?json=true`, {
    method: 'POST',
    headers: {
      'Content-Type': 'application/x-www-form-urlencoded',
      Cookie: csrfCookie,
    },
    body: new URLSearchParams({
      csrfToken: String(csrfBody.csrfToken || ''),
      email,
      password,
      callbackUrl: baseUrl,
      json: 'true',
    }),
  });

  const body = await response.json().catch(() => ({}));
  const cookieHeader = cookiesFromSetCookieHeaders(collectSetCookieHeaders(response.headers));

  if (!response.ok || body?.error) {
    throw new Error(body?.error || `Login failed (${response.status})`);
  }

  const mergedCookieHeader = mergeCookieHeader(csrfCookie, cookieHeader);
  writeCliSession({
    cookieHeader: mergedCookieHeader,
    baseUrl,
    updatedAt: new Date().toISOString(),
  });

  return {
    cookieHeader: mergedCookieHeader,
    body,
  };
}

async function linkCliDevice(baseUrl, cookieHeader, deviceLabel) {
  const startResponse = await fetch(`${baseUrl}/api/control-plane/devices/link/start`, {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
      Cookie: cookieHeader,
    },
    body: JSON.stringify({ deviceLabel }),
  });

  const startBody = await startResponse.json().catch(() => ({}));
  if (!startResponse.ok || !startBody.ok) {
    throw new Error(startBody.error || `Device link start failed (${startResponse.status})`);
  }

  const completeResponse = await fetch(`${baseUrl}/api/control-plane/devices/link/complete`, {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
    },
    body: JSON.stringify({
      linkCode: startBody.link.linkCode,
      deviceLabel,
      metadata: {
        client: 'elyan-cli',
        platform: process.platform,
        hostname: os.hostname(),
        releaseTag: `v${packageJson.version}`,
      },
    }),
  });

  const completeBody = await completeResponse.json().catch(() => ({}));
  if (!completeResponse.ok || !completeBody.ok) {
    throw new Error(completeBody.error || `Device link completion failed (${completeResponse.status})`);
  }

  const session = readCliSession() || {};
  session.deviceToken = completeBody.device.deviceToken;
  session.deviceId = completeBody.device.deviceId;
  session.deviceLabel = completeBody.device.deviceLabel;
  session.lastSeenReleaseTag = completeBody.device.lastSeenReleaseTag || `v${packageJson.version}`;
  session.updatedAt = new Date().toISOString();
  writeCliSession(session);

  return completeBody.device;
}

async function syncCliDevice(baseUrl, deviceToken, metadata = {}) {
  if (!deviceToken) {
    return null;
  }

  const response = await fetch(`${baseUrl}/api/control-plane/devices/sync/push`, {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
      'x-elyan-device-token': deviceToken,
    },
    body: JSON.stringify({
      lastSeenReleaseTag: `v${packageJson.version}`,
      metadata: {
        client: 'elyan-cli',
        platform: process.platform,
        hostname: os.hostname(),
        ...metadata,
      },
    }),
  });

  const body = await response.json().catch(() => ({}));
  if (!response.ok || !body?.ok) {
    throw new Error(body?.error || `Device sync failed (${response.status})`);
  }

  const session = readCliSession() || {};
  session.deviceId = body.device.deviceId ?? session.deviceId;
  session.deviceLabel = body.device.deviceLabel ?? session.deviceLabel;
  session.lastSeenAt = body.device.lastSeenAt ?? new Date().toISOString();
  session.lastSeenReleaseTag = body.device.lastSeenReleaseTag ?? `v${packageJson.version}`;
  session.updatedAt = new Date().toISOString();
  writeCliSession(session);

  return body.device;
}

function maskDeviceToken(deviceToken) {
  if (!deviceToken) {
    return 'not stored';
  }

  return `...${String(deviceToken).slice(-8)}`;
}

function printLinkedDeviceSnapshot(session = readCliSession()) {
  if (!session?.deviceId && !session?.deviceLabel) {
    console.log(`Linked device: ${chalk.gray('none')}`);
    return;
  }

  console.log(`Linked device: ${chalk.green(session.deviceLabel || 'Elyan CLI')}${session.deviceId ? ` (${session.deviceId})` : ''}`);
  console.log(`Device release: ${chalk.green(session.lastSeenReleaseTag || `v${packageJson.version}`)}`);
  console.log(`Device token: ${chalk.gray(maskDeviceToken(session.deviceToken))}`);
  console.log(`Token rotation: ${session.deviceToken ? chalk.green('ready') : chalk.yellow('not linked')}`);
}

function printAccountSnapshot(data) {
  console.log(chalk.bold.blue('\n👤 Hosted account\n'));
  console.log(`Email: ${chalk.green(data.session.email || 'unknown')}`);
  console.log(`Name: ${chalk.green(data.session.name || data.account.displayName)}`);
  console.log(`Account: ${chalk.green(data.account.accountId)}`);
  console.log(`Plan: ${chalk.green(`${data.account.plan.title} (${data.account.subscription.status})`)}`);
  console.log(`Hosted access: ${data.account.entitlements.hostedAccess ? chalk.green('active') : chalk.yellow('inactive')}`);
  console.log(`Monthly credits remaining: ${chalk.green(data.account.usageSnapshot.monthlyCreditsRemaining)}`);
  console.log(`Daily requests remaining: ${chalk.green(String(data.account.usageSnapshot.remainingRequests))}`);
  console.log(`Daily tool calls remaining: ${chalk.green(String(data.account.usageSnapshot.remainingHostedToolActionCalls))}`);
  console.log(`Reset at: ${chalk.green(new Date(data.account.usageSnapshot.resetAt).toLocaleString())}`);
}

function deepClone(value) {
  return JSON.parse(JSON.stringify(value));
}

function deepMerge(base, patch) {
  const result = Array.isArray(base) ? [...base] : { ...base };

  for (const [key, value] of Object.entries(patch || {})) {
    if (value === undefined) continue;
    if (
      value &&
      typeof value === 'object' &&
      !Array.isArray(value) &&
      result[key] &&
      typeof result[key] === 'object' &&
      !Array.isArray(result[key])
    ) {
      result[key] = deepMerge(result[key], value);
    } else {
      result[key] = value;
    }
  }

  return result;
}

function parseLooseValue(raw) {
  if (raw === 'true') return true;
  if (raw === 'false') return false;
  if (raw === 'null') return null;
  if (raw === '' || raw === undefined) return raw;

  const numeric = Number(raw);
  if (Number.isFinite(numeric) && String(numeric) === raw) {
    return numeric;
  }

  try {
    return JSON.parse(raw);
  } catch {
    return raw;
  }
}

function setDeepValue(target, pathExpression, value) {
  const keys = pathExpression.split('.').filter(Boolean);
  if (keys.length === 0) return target;

  let cursor = target;
  for (let index = 0; index < keys.length - 1; index += 1) {
    const key = keys[index];
    if (!cursor[key] || typeof cursor[key] !== 'object') {
      cursor[key] = {};
    }
    cursor = cursor[key];
  }

  cursor[keys[keys.length - 1]] = value;
  return target;
}

function getDeepValue(target, pathExpression) {
  return pathExpression.split('.').reduce((cursor, key) => {
    if (!cursor || typeof cursor !== 'object') return undefined;
    return cursor[key];
  }, target);
}

function printRuntimeSettingsSummary(settings) {
  console.log(chalk.bold.blue('\n⚙️ Runtime settings\n'));
  console.log(`Routing mode: ${chalk.green(settings.routing.routingMode)}`);
  console.log(`Preferred model: ${chalk.green(settings.routing.preferredModelId || 'auto')}`);
  console.log(`Search enabled: ${chalk.green(String(Boolean(settings.routing.searchEnabled)))}`);
  console.log(`Voice enabled: ${chalk.green(String(Boolean(settings.voice.enabled)))}`);
  console.log(`MCP servers: ${chalk.green(String(settings.mcp.servers.length))}`);
}

function escapeRegex(value) {
  return value.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
}

async function probeService(label, url, timeoutMs = 3000) {
  const controller = new AbortController();
  const timeout = setTimeout(() => controller.abort(), timeoutMs);

  try {
    const response = await fetch(url, { signal: controller.signal });
    return {
      label,
      ok: response.ok,
      status: response.status,
    };
  } catch (error) {
    return {
      label,
      ok: false,
      status: error instanceof Error ? error.message : 'unreachable',
    };
  } finally {
    clearTimeout(timeout);
  }
}

async function fetchJson(url, timeoutMs = 5000, init = {}) {
  const controller = new AbortController();
  const timeout = setTimeout(() => controller.abort(), timeoutMs);

  try {
    const response = await fetch(url, {
      ...init,
      signal: controller.signal,
      headers: {
        ...(init.headers || {}),
      },
    });
    const body = await response.text();
    let data;

    try {
      data = body ? JSON.parse(body) : null;
    } catch {
      data = body;
    }

    return {
      ok: response.ok,
      status: response.status,
      data,
    };
  } catch (error) {
    return {
      ok: false,
      status: error instanceof Error ? error.message : 'unreachable',
      data: null,
    };
  } finally {
    clearTimeout(timeout);
  }
}

function applyZeroCostRuntimeSettings(settings, model = RECOMMENDED_LOCAL_MODEL) {
  const next = deepClone(settings);
  next.routing.routingMode = 'local_only';
  next.routing.preferredModelId = `ollama:${model}`;
  next.routing.searchEnabled = false;
  next.team = next.team || createDefaultRuntimeSettings().team;
  next.team.allowCloudEscalation = false;
  return next;
}

function runBootstrap({ zeroCost = false, fix = false, model = RECOMMENDED_LOCAL_MODEL } = {}) {
  ensureRuntimeStorageDirs();
  const envResult = ensureGlobalEnvDefaults(
    {
      ELYAN_STORAGE_DIR: DEFAULT_STORAGE_DIR,
      ELYAN_RUNTIME_SETTINGS_PATH: LOCAL_RUNTIME_SETTINGS,
      OLLAMA_URL: 'http://127.0.0.1:11434',
      SEARXNG_URL: 'http://localhost:8080',
    },
    { backup: fix }
  );

  const settings = readRuntimeSettingsFile();
  const nextSettings = zeroCost ? applyZeroCostRuntimeSettings(settings, model) : settings;
  writeRuntimeSettingsFile(nextSettings);

  return {
    envChanged: envResult.changed,
    envPath: envResult.path,
    settingsPath: LOCAL_RUNTIME_SETTINGS,
    zeroCost,
    model,
  };
}

function getLaunchdPlistPath() {
  return path.join(os.homedir(), 'Library', 'LaunchAgents', `${LAUNCHD_LABEL}.plist`);
}

function getSystemdUnitPath() {
  return path.join(os.homedir(), '.config', 'systemd', 'user', 'elyan.service');
}

function buildLaunchdPlist() {
  const nodePath = process.execPath;
  const cliPath = path.join(__dirname, 'elyan.js');
  return `<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key><string>${LAUNCHD_LABEL}</string>
  <key>WorkingDirectory</key><string>${process.cwd()}</string>
  <key>ProgramArguments</key>
  <array>
    <string>${nodePath}</string>
    <string>${cliPath}</string>
    <string>start</string>
  </array>
  <key>RunAtLoad</key><true/>
  <key>KeepAlive</key><true/>
  <key>StandardOutPath</key><string>${path.join(GLOBAL_DIR, 'elyan.out.log')}</string>
  <key>StandardErrorPath</key><string>${path.join(GLOBAL_DIR, 'elyan.err.log')}</string>
</dict>
</plist>
`;
}

function buildSystemdUnit() {
  return `[Unit]
Description=Elyan local runtime
After=network.target

[Service]
Type=simple
WorkingDirectory=${process.cwd()}
ExecStart=${process.execPath} ${path.join(__dirname, 'elyan.js')} start
Restart=on-failure
RestartSec=5

[Install]
WantedBy=default.target
`;
}

function installUserService() {
  ensureGlobalConfigDir();
  if (process.platform === 'darwin') {
    const plistPath = getLaunchdPlistPath();
    atomicWriteFileSync(plistPath, buildLaunchdPlist());
    return { platform: 'launchd', path: plistPath };
  }

  if (process.platform === 'linux') {
    const unitPath = getSystemdUnitPath();
    atomicWriteFileSync(unitPath, buildSystemdUnit());
    return { platform: 'systemd-user', path: unitPath };
  }

  throw new Error(`Service install is not implemented for ${process.platform}.`);
}

function controlUserService(action) {
  if (process.platform === 'darwin') {
    const plistPath = getLaunchdPlistPath();
    const argsByAction = {
      start: ['bootstrap', 'gui', `${process.getuid()}`, plistPath],
      stop: ['bootout', 'gui', `${process.getuid()}`, plistPath],
      status: ['print', `gui/${process.getuid()}/${LAUNCHD_LABEL}`],
    };
    return spawnSync('launchctl', argsByAction[action], { stdio: 'inherit' });
  }

  if (process.platform === 'linux') {
    const argsByAction = {
      start: ['--user', 'start', 'elyan.service'],
      stop: ['--user', 'stop', 'elyan.service'],
      status: ['--user', 'status', 'elyan.service'],
    };
    return spawnSync('systemctl', argsByAction[action], { stdio: 'inherit' });
  }

  throw new Error(`Service control is not implemented for ${process.platform}.`);
}

function printChannelStatusLine(name, status) {
  const enabled = status.enabled ? chalk.green('enabled') : chalk.gray('disabled');
  const configured = status.configured ? chalk.green('configured') : chalk.yellow('missing config');
  console.log(`- ${chalk.bold(name)}: ${enabled}, ${configured}`);
  if (status.costProfile) {
    console.log(`  Cost: ${status.costProfile}`);
  }
  if (status.webhookPath) {
    console.log(`  Webhook: ${status.webhookPath}`);
  }
}

// ----------------------------------------------------------------------------
// COMMAND: bootstrap
// ----------------------------------------------------------------------------
program
  .command('bootstrap')
  .option('--zero-cost', 'Configure local-only routing and keep paid/cloud surfaces disabled')
  .option('--model <model>', 'Recommended Ollama model to prefer', RECOMMENDED_LOCAL_MODEL)
  .description('Prepares local Elyan storage, runtime settings, and safe environment defaults.')
  .action((options) => {
    const result = runBootstrap({
      zeroCost: Boolean(options.zeroCost),
      fix: true,
      model: options.model || RECOMMENDED_LOCAL_MODEL,
    });

    console.log(chalk.bold.blue('\n🧰 Elyan bootstrap\n'));
    console.log(`Storage: ${chalk.green(path.resolve(process.cwd(), DEFAULT_STORAGE_DIR))}`);
    console.log(`Settings: ${chalk.green(result.settingsPath)}`);
    console.log(`Global env: ${chalk.green(result.envPath)}${result.envChanged ? ' updated' : ' ready'}`);
    if (result.zeroCost) {
      console.log(`Routing: ${chalk.green(`local_only via ollama:${result.model}`)}`);
    }
    console.log(chalk.gray('Next: run `elyan models setup` and then `elyan doctor`.'));
  });

// ----------------------------------------------------------------------------
// COMMAND: setup
// ----------------------------------------------------------------------------
program
  .command('setup')
  .option('--zero-cost', 'Configure local-only routing and keep paid/cloud surfaces disabled')
  .option('--model <model>', 'Recommended Ollama model to prefer', RECOMMENDED_LOCAL_MODEL)
  .option('--probe-timeout-ms <ms>', 'Timeout for local service probes', '3000')
  .description('Guides a first local Elyan setup without requiring hosted account linking.')
  .action(async (options) => {
    const model = options.model || RECOMMENDED_LOCAL_MODEL;
    const probeTimeoutMs = Number.parseInt(options.probeTimeoutMs, 10) || 3000;

    console.log(chalk.bold.blue('\nElyan setup\n'));
    loadEnvSafe();

    const bootstrap = runBootstrap({
      zeroCost: Boolean(options.zeroCost),
      fix: true,
      model,
    });

    const ollamaUrl = process.env.OLLAMA_URL || 'http://127.0.0.1:11434';
    const searxngUrl = process.env.SEARXNG_URL || 'http://localhost:8080';
    const [ollamaProbe, searxngProbe] = await Promise.all([
      probeService('Ollama', `${ollamaUrl.replace(/\/$/, '')}/api/version`, probeTimeoutMs),
      probeService('SearXNG', `${searxngUrl.replace(/\/$/, '')}/healthz`, probeTimeoutMs),
    ]);

    console.log(`Storage: ${chalk.green(path.resolve(process.cwd(), DEFAULT_STORAGE_DIR))}`);
    console.log(`Settings: ${chalk.green(bootstrap.settingsPath)}`);
    console.log(`Global env: ${chalk.green(bootstrap.envPath)}${bootstrap.envChanged ? ' updated' : ' ready'}`);
    console.log(`Routing: ${bootstrap.zeroCost ? chalk.green(`local_only via ollama:${bootstrap.model}`) : chalk.green('local_first')}`);
    console.log(`Ollama: ${ollamaProbe.ok ? chalk.green('reachable') : chalk.yellow(`not reachable (${ollamaProbe.status})`)}`);
    console.log(`Search: ${searxngProbe.ok ? chalk.green('reachable') : chalk.gray(`optional / offline (${searxngProbe.status})`)}`);

    if (bootstrap.zeroCost && !ollamaProbe.ok) {
      console.log(chalk.yellow(`\nNext: start Ollama and run ${chalk.gray(`elyan models setup --model ${model}`)}.`));
    } else {
      console.log(chalk.green('\nLocal setup files are ready.'));
    }

    console.log(chalk.gray('Then run `npm run dev`, open `/manage`, and use `elyan login` only when hosted account linking is needed.'));
  });

// ----------------------------------------------------------------------------
// COMMAND: doctor
// ----------------------------------------------------------------------------
program
  .command('doctor')
  .option('--fix', 'Create missing local config, storage directories, and safe defaults')
  .option('--zero-cost', 'Prefer local-only routing and disable optional cloud/search dependencies')
  .description('Checks the local runtime, optional search backend, and configured provider keys.')
  .action(async (options) => {
    console.log(chalk.bold.blue('\n🏥 Elyan Doctor - Checking system dependencies\n'));
    let errors = 0;

    // Check Env
    loadEnvSafe();
    if (options.fix) {
      const bootstrap = runBootstrap({ zeroCost: options.zeroCost, fix: true });
      console.log(`✅ ${chalk.green('Bootstrap files:')} ${bootstrap.settingsPath}`);
      console.log(`✅ ${chalk.green('Global env:')} ${bootstrap.envPath}${bootstrap.envChanged ? ' updated' : ' already ready'}`);
    }

    const ollamaUrl = process.env.OLLAMA_URL || 'http://127.0.0.1:11434';
    const searxngUrl = process.env.SEARXNG_URL || 'http://localhost:8080';
    const settings = readRuntimeSettingsFile();

    const [searxngProbe, ollamaProbe] = await Promise.all([
      probeService('SearxNG', `${searxngUrl.replace(/\/$/, '')}/healthz`),
      probeService('Ollama', `${ollamaUrl.replace(/\/$/, '')}/api/version`),
    ]);

    if (searxngProbe.ok) {
      console.log(`✅ ${chalk.green('SearxNG:')} Reachable at ${searxngUrl}`);
    } else {
      console.log(`⚠️  ${chalk.yellow('SearxNG:')} Unreachable at ${searxngUrl} (${searxngProbe.status}). Optional for live web retrieval.`);
    }

    if (ollamaProbe.ok) {
      console.log(`✅ ${chalk.green('Ollama:')} Reachable at ${ollamaUrl}`);
    } else {
      console.log(`⚠️  ${chalk.yellow('Ollama:')} Unreachable at ${ollamaUrl} (${ollamaProbe.status}).`);
    }

    const hasAnyCloudProvider =
      Boolean(process.env.OPENAI_API_KEY) || Boolean(process.env.ANTHROPIC_API_KEY) || Boolean(process.env.GROQ_API_KEY);
    const hasUsableModelSource = ollamaProbe.ok || hasAnyCloudProvider;

    if (!hasUsableModelSource && settings.routing.routingMode !== 'local_only') {
      console.log(`❌ ${chalk.red('Model source:')} No Ollama connection or cloud API key found.`);
      errors++;
    } else if (!hasUsableModelSource) {
      console.log(`⚠️  ${chalk.yellow('Model source:')} Local-only mode is selected, but Ollama is not reachable yet.`);
      errors++;
    } else if (ollamaProbe.ok) {
      console.log(`✅ ${chalk.green('Model source:')} Ollama is reachable.`);
    } else if (hasAnyCloudProvider) {
      console.log(`✅ ${chalk.green('Model source:')} Cloud provider key configured.`);
    }

    if (process.env.DATABASE_URL) {
      console.log(`✅ ${chalk.green('Control-plane DB:')} PostgreSQL configured for optional hosted control-plane use.`);
    } else {
      console.log(
        `⚠️  ${chalk.yellow('Control-plane DB:')} Not configured. Fine for local-only Elyan.`
      );
    }

    console.log(`Local operator: ${settings.localAgent.enabled ? chalk.green('enabled') : chalk.gray('disabled')} (${settings.localAgent.allowedRoots.length} allowed root)`);
    console.log(`Zero-cost routing: ${settings.routing.routingMode === 'local_only' ? chalk.green('on') : chalk.gray('off')}`);

    console.log(`\n🩺 ${chalk.bold('Resolution:')} ${errors > 0 ? chalk.red('Issues found.') : chalk.green('Local runtime ready.')}`);
    if (errors === 0) {
      console.log(`Next: ${chalk.gray('npm run dev')} or ${chalk.gray('npm run start')} after build, then check ${chalk.gray('http://localhost:3000/api/healthz')}.`);
    }
    if (errors > 0) process.exit(1);
  });

// ----------------------------------------------------------------------------
// COMMAND: capabilities
// ----------------------------------------------------------------------------
program
  .command('capabilities')
  .option('--json', 'Print raw JSON instead of a guided summary')
  .option('--base-url <url>', 'Base URL for the running Elyan app', 'http://localhost:3000')
  .description('Fetches the local capability catalog from the app runtime.')
  .action(async (options) => {
    const baseUrl = options.baseUrl.replace(/\/$/, '');
    const result = await fetchJson(`${baseUrl}/api/capabilities`);

    if (!result.ok) {
      console.log(chalk.red(`Failed to fetch capability catalog (${result.status}).`));
      process.exit(1);
      return;
    }

    if (options.json) {
      console.log(JSON.stringify(result.data, null, 2));
      return;
    }

    const data = result.data;
    console.log(chalk.bold.blue('\n🧩 Capability catalog\n'));
    console.log(`Execution model: ${chalk.green(data.executionModel ?? 'local_module_first')}`);
    console.log(`Local capabilities: ${chalk.green(String(data.summary?.localCapabilityCount ?? 0))}`);
    console.log(`Local bridge tools: ${chalk.green(String(data.summary?.bridgeToolCount ?? 0))}`);
    console.log(`MCP tools: ${chalk.green(String(data.summary?.mcpToolCount ?? 0))}`);
    console.log(`MCP resources: ${chalk.green(String(data.summary?.mcpResourceCount ?? 0))}`);
    console.log(`MCP prompts: ${chalk.green(String(data.summary?.mcpPromptCount ?? 0))}`);
    console.log('\nSelection guide:');
    for (const entry of data.selectionGuide ?? []) {
      console.log(`- ${chalk.bold(entry.title)} (${entry.kind})`);
      console.log(`  When: ${entry.when}`);
      console.log(`  Why: ${entry.why}`);
    }
  });

// ----------------------------------------------------------------------------
// COMMAND: plans
// ----------------------------------------------------------------------------
program
  .command('plans')
  .option('--base-url <url>', 'Base URL for the running Elyan app', 'http://localhost:3000')
  .description('Fetches the shared control-plane plan catalog.')
  .action(async (options) => {
    const baseUrl = options.baseUrl.replace(/\/$/, '');
    const result = await fetchJson(`${baseUrl}/api/control-plane/plans`);

    if (!result.ok) {
      console.log(chalk.red(`Failed to fetch control-plane plans (${result.status}).`));
      process.exit(1);
      return;
    }

    console.log(chalk.bold.blue('\n💳 Control-plane plans\n'));
    console.log(JSON.stringify(result.data, null, 2));
  });

// ----------------------------------------------------------------------------
// COMMAND: login
// ----------------------------------------------------------------------------
program
  .command('login')
  .option('--base-url <url>', 'Base URL for the running Elyan app', 'http://localhost:3000')
  .requiredOption('--email <email>', 'Hosted account email')
  .requiredOption('--password <password>', 'Hosted account password')
  .option('--device-label <label>', 'Device label to register for this CLI', `Elyan CLI on ${os.hostname()}`)
  .description('Signs in to the hosted control plane and links this CLI as a device.')
  .action(async (options) => {
    const baseUrl = getCliBaseUrl(options.baseUrl);

    try {
      const session = await loginToHostedControlPlane(baseUrl, options.email, options.password);
      const device = await linkCliDevice(baseUrl, session.cookieHeader, options.deviceLabel);
      const syncedDevice = await syncCliDevice(baseUrl, device.deviceToken).catch(() => null);
      console.log(chalk.green('✅ Logged in to the hosted control plane.'));
      console.log(`Device linked: ${chalk.green(device.deviceLabel)} (${device.deviceId})`);
      console.log(`Device release: ${chalk.green(syncedDevice?.lastSeenReleaseTag || `v${packageJson.version}`)}`);
      console.log(`Token rotation: ${chalk.green('ready')} (${maskDeviceToken(device.deviceToken)})`);
    } catch (error) {
      console.log(chalk.red(error instanceof Error ? error.message : 'Login failed'));
      process.exit(1);
    }
  });

// ----------------------------------------------------------------------------
// COMMAND: whoami
// ----------------------------------------------------------------------------
program
  .command('whoami')
  .option('--base-url <url>', 'Base URL for the running Elyan app', 'http://localhost:3000')
  .description('Shows the current hosted account bound to the local CLI session.')
  .action(async (options) => {
    const baseUrl = getCliBaseUrl(options.baseUrl);
    const result = await fetchAuthedJson(`${baseUrl}/api/control-plane/auth/me`);

    if (!result.ok) {
      console.log(chalk.red(`Not logged in or session is invalid (${result.status}).`));
      process.exit(1);
      return;
    }

    printAccountSnapshot(result.data);
    printLinkedDeviceSnapshot();
  });

// ----------------------------------------------------------------------------
// COMMAND: plan
// ----------------------------------------------------------------------------
program
  .command('plan')
  .option('--base-url <url>', 'Base URL for the running Elyan app', 'http://localhost:3000')
  .description('Shows the current hosted plan and the available upgrade catalog.')
  .action(async (options) => {
    const baseUrl = getCliBaseUrl(options.baseUrl);
    const [sessionResult, plansResult] = await Promise.all([
      fetchAuthedJson(`${baseUrl}/api/control-plane/panel`),
      fetchJson(`${baseUrl}/api/control-plane/plans`),
    ]);

    if (!sessionResult.ok) {
      console.log(chalk.red(`Not logged in or session is invalid (${sessionResult.status}).`));
      process.exit(1);
      return;
    }

    console.log(chalk.bold.blue('\n📦 Current plan\n'));
    console.log(`Plan: ${chalk.green(sessionResult.data.account.plan.title)}`);
    console.log(`Status: ${chalk.green(sessionResult.data.account.subscription.status)}`);
    console.log(`Hosted access: ${sessionResult.data.account.entitlements.hostedAccess ? chalk.green('active') : chalk.yellow('inactive')}`);
    console.log(`Billing state: ${chalk.green(sessionResult.data.account.subscription.syncState)}`);

    if (plansResult.ok && plansResult.data?.plans) {
      console.log(chalk.bold.blue('\n💳 Upgrade catalog\n'));
      for (const plan of plansResult.data.plans) {
        console.log(`- ${chalk.bold(plan.title)} (${plan.id})`);
        console.log(`  ${plan.pricing.monthlyPriceTRY} TRY, ${plan.pricing.monthlyIncludedCredits} credits`);
        console.log(`  Daily: ${plan.dailyLimits.hostedRequestsPerDay} requests / ${plan.dailyLimits.hostedToolActionCallsPerDay} tool calls`);
      }
    }
  });

// ----------------------------------------------------------------------------
// COMMAND: usage
// ----------------------------------------------------------------------------
program
  .command('usage')
  .option('--base-url <url>', 'Base URL for the running Elyan app', 'http://localhost:3000')
  .description('Shows daily hosted usage, remaining credits, and recent usage ledger entries.')
  .action(async (options) => {
    const baseUrl = getCliBaseUrl(options.baseUrl);
    const result = await fetchAuthedJson(`${baseUrl}/api/control-plane/panel`);

    if (!result.ok) {
      console.log(chalk.red(`Not logged in or session is invalid (${result.status}).`));
      process.exit(1);
      return;
    }

    const { account, ledger } = result.data;
    console.log(chalk.bold.blue('\n📈 Hosted usage\n'));
    console.log(`Monthly credits remaining: ${chalk.green(account.usageSnapshot.monthlyCreditsRemaining)}`);
    console.log(`Monthly credits burned: ${chalk.green(account.usageSnapshot.monthlyCreditsBurned)}`);
    console.log(`Daily requests: ${chalk.green(`${account.usageSnapshot.dailyRequests}/${account.usageSnapshot.dailyRequestsLimit}`)}`);
    console.log(`Daily tool calls: ${chalk.green(`${account.usageSnapshot.dailyHostedToolActionCalls}/${account.usageSnapshot.dailyHostedToolActionCallsLimit}`)}`);
    console.log(`Reset at: ${chalk.green(new Date(account.usageSnapshot.resetAt).toLocaleString())}`);
    console.log(`Limit state: ${chalk.green(account.usageSnapshot.state)}`);

    if (Array.isArray(ledger) && ledger.length > 0) {
      console.log(chalk.bold.blue('\nRecent ledger\n'));
      for (const entry of ledger.slice(0, 5)) {
        console.log(`- ${chalk.bold(entry.kind)} ${entry.creditsDelta} ${entry.domain ?? ''}`.trim());
        console.log(`  ${entry.note ?? entry.balanceAfter}`);
      }
    }
  });

// ----------------------------------------------------------------------------
// COMMAND: limits
// ----------------------------------------------------------------------------
program
  .command('limits')
  .option('--base-url <url>', 'Base URL for the running Elyan app', 'http://localhost:3000')
  .description('Shows the hosted daily guardrails and the current remaining headroom.')
  .action(async (options) => {
    const baseUrl = getCliBaseUrl(options.baseUrl);
    const result = await fetchAuthedJson(`${baseUrl}/api/control-plane/panel`);

    if (!result.ok) {
      console.log(chalk.red(`Not logged in or session is invalid (${result.status}).`));
      process.exit(1);
      return;
    }

    const { account } = result.data;
    console.log(chalk.bold.blue('\n🛡️ Hosted limits\n'));
    console.log(`Daily requests: ${chalk.green(`${account.usageSnapshot.remainingRequests}/${account.usageSnapshot.dailyRequestsLimit}`)} remaining`);
    console.log(`Daily tool calls: ${chalk.green(`${account.usageSnapshot.remainingHostedToolActionCalls}/${account.usageSnapshot.dailyHostedToolActionCallsLimit}`)} remaining`);
    console.log(`Resets at: ${chalk.green(new Date(account.usageSnapshot.resetAt).toLocaleString())}`);
    console.log(`Plan state: ${chalk.green(account.usageSnapshot.state)}`);
  });

// ----------------------------------------------------------------------------
// COMMAND: logout
// ----------------------------------------------------------------------------
program
  .command('logout')
  .option('--base-url <url>', 'Base URL for the running Elyan app', 'http://localhost:3000')
  .description('Clears the local CLI session and unlinks the registered device.')
  .action(async (options) => {
    const baseUrl = getCliBaseUrl(options.baseUrl);
    const session = readCliSession();

    try {
      if (session?.deviceToken) {
        const response = await fetch(`${baseUrl}/api/control-plane/devices/unlink`, {
          method: 'POST',
          headers: {
            'Content-Type': 'application/json',
            'x-elyan-device-token': session.deviceToken,
          },
        });

        if (!response.ok) {
          const body = await response.json().catch(() => ({}));
          console.log(chalk.yellow(body.error || `Device unlink failed (${response.status})`));
        }
      }
    } finally {
      clearCliSession();
    }

    console.log(chalk.green('✅ Local CLI session cleared.'));
  });

// ----------------------------------------------------------------------------
// COMMAND: upgrade
// ----------------------------------------------------------------------------
program
  .command('upgrade')
  .option('--base-url <url>', 'Base URL for the running Elyan app', 'http://localhost:3000')
  .description('Shows the current upgrade path and the hosted plan catalog.')
  .action(async (options) => {
    const baseUrl = getCliBaseUrl(options.baseUrl);
    const [panelResult, plansResult] = await Promise.all([
      fetchAuthedJson(`${baseUrl}/api/control-plane/panel`),
      fetchJson(`${baseUrl}/api/control-plane/plans`),
    ]);

    console.log(chalk.bold.blue('\n⬆️ Upgrade path\n'));

    if (panelResult.ok) {
      const account = panelResult.data.account;
      if (!account.entitlements.hostedAccess) {
        console.log(`Current plan: ${chalk.green(account.plan.title)}`);
        console.log(`Suggested next step: open ${chalk.green(`${baseUrl}/pricing`)}`);
      } else if (account.subscription.syncState !== 'synced') {
        console.log(`Hosted billing is ${chalk.yellow(account.subscription.syncState)}.`);
        console.log(`Finish checkout at ${chalk.green(`${baseUrl}/auth`)}`);
      } else {
        console.log(`Plan: ${chalk.green(account.plan.title)}`);
        console.log(`Hosted usage is already active. Use ${chalk.green('limits')} or ${chalk.green('usage')} to watch headroom.`);
      }
    } else {
      console.log(chalk.yellow('No hosted session is available. Visit /pricing to compare plans.'));
    }

    if (plansResult.ok && plansResult.data?.plans) {
      console.log(chalk.bold.blue('\nAvailable hosted plans\n'));
      for (const plan of plansResult.data.plans.filter((entry) => entry.entitlements.hostedAccess)) {
        console.log(`- ${chalk.bold(plan.title)}: ${plan.monthlyPriceTRY} TRY, ${plan.monthlyIncludedCredits} credits`);
      }
    }
  });

// ----------------------------------------------------------------------------
// COMMAND: update
// ----------------------------------------------------------------------------
program
  .command('update')
  .description('Updates Elyan using the smallest supported path for the current installation.')
  .action(async () => {
    console.log(chalk.bold.blue('\n⬆️ Elyan update\n'));

    if (isSourceCheckout(__dirname)) {
      console.log(chalk.yellow('This is a source checkout, so automatic self-update is not used here.'));
      console.log(`Run: ${chalk.gray('git pull --ff-only && npm install && npm run build')}`);
      return;
    }

    if (isHomebrewInstall() && commandExists('brew')) {
      console.log(chalk.gray('Updating via Homebrew...'));
      await runCommand('brew', ['update']);
      await runCommand('brew', ['upgrade', 'elyan']);
      console.log(chalk.green('Elyan updated via Homebrew.'));
      return;
    }

    const npmBin = /^win/.test(process.platform) ? 'npm.cmd' : 'npm';
    if (!commandExists(npmBin)) {
      console.log(chalk.red('npm is not available on this machine.'));
      process.exit(1);
      return;
    }

    console.log(chalk.gray('Updating via npm global package...'));
    await runCommand(npmBin, ['install', '-g', 'elyan@latest']);
    console.log(chalk.green('Elyan updated via npm.'));
  });

// ----------------------------------------------------------------------------
// COMMAND: health
// ----------------------------------------------------------------------------
program
  .command('health')
  .option('--base-url <url>', 'Base URL for the running Elyan app', 'http://localhost:3000')
  .description('Checks the local runtime health endpoint and reports shared control-plane status.')
  .action(async (options) => {
    const baseUrl = options.baseUrl.replace(/\/$/, '');
    const [localHealth, sharedHealth] = await Promise.all([
      fetchJson(`${baseUrl}/api/healthz`),
      fetchJson(`${baseUrl}/api/control-plane/health`),
    ]);

    console.log(chalk.bold.blue('\n🩺 Elyan health\n'));
    console.log(`Local runtime: ${localHealth.ok ? chalk.green('ok') : chalk.red(localHealth.status)}`);
    console.log(`Shared control plane: ${sharedHealth.ok ? chalk.green('ok') : chalk.yellow(sharedHealth.status)}`);
    if (sharedHealth.ok && sharedHealth.data && typeof sharedHealth.data === 'object' && sharedHealth.data.storage) {
      console.log(`Control plane DB: ${chalk.green(String(sharedHealth.data.storage))}`);
    }

    if (localHealth.ok && localHealth.data && typeof localHealth.data === 'object') {
      const body = localHealth.data;
      console.log(`Runtime ready: ${body.ready ? chalk.green('yes') : chalk.yellow('no')}`);

      if (body.checks?.search) {
        console.log(`Search: ${body.checks.search.ok ? chalk.green('ready') : chalk.yellow('not ready')}`);
      }

      if (body.checks?.models) {
        console.log(
          `Models: ${body.checks.models.ok ? chalk.green(`${body.checks.models.count} available`) : chalk.yellow('not ready')}`
        );
      }

      if (body.checks?.mcp) {
        console.log(`MCP: ${body.checks.mcp.configured ? chalk.green('configured') : chalk.gray('optional / not configured')}`);
      }
    }

    if (!localHealth.ok) {
      process.exit(1);
    }
  });

// ----------------------------------------------------------------------------
// COMMAND: config
// ----------------------------------------------------------------------------
program
  .command('config <action> [key] [value]')
  .description('Manage global Elyan config in ~/.elyan/.env')
  .action((action, key, value) => {
    ensureGlobalConfigDir();
    let currentConfig = fs.existsSync(GLOBAL_ENV) ? fs.readFileSync(GLOBAL_ENV, 'utf-8') : '';

    if (action === 'set' && key && value) {
      const regex = new RegExp(`^${escapeRegex(key)}=.*$`, 'm');
      if (regex.test(currentConfig)) {
        currentConfig = currentConfig.replace(regex, `${key}=${value}`);
      } else {
        currentConfig += `\n${key}=${value}`;
      }
      fs.writeFileSync(GLOBAL_ENV, currentConfig.trim() + '\n');
      console.log(chalk.green(`✔️ Set ${key} successfully in ${GLOBAL_ENV}`));
    } else if (action === 'view') {
      console.log(chalk.blue(`\n📄 Current configuration (${GLOBAL_ENV}):\n`));
      console.log(currentConfig || chalk.gray('No configurations found.'));
    } else {
      console.log(chalk.red('Usage: elyan config set <KEY> <VALUE> | elyan config view'));
    }
  });

// ----------------------------------------------------------------------------
// COMMAND: models
// ----------------------------------------------------------------------------
program
  .command('models [action]')
  .option('--model <model>', 'Ollama model for local setup', RECOMMENDED_LOCAL_MODEL)
  .option('--no-pull', 'Only update Elyan settings; do not run ollama pull')
  .description('Shows configured providers or prepares the recommended local model.')
  .action(async (action, options) => {
    console.log(chalk.bold.blue('\n🧠 Checking models availability...\n'));
    loadEnvSafe();
    const model = options.model || RECOMMENDED_LOCAL_MODEL;

    if (action === 'setup') {
      const settings = applyZeroCostRuntimeSettings(readRuntimeSettingsFile(), model);
      writeRuntimeSettingsFile(settings);

      if (options.pull) {
        if (!commandExists('ollama')) {
          console.log(chalk.yellow('Ollama CLI is not available. Install Ollama, then run this command again.'));
          console.log(chalk.gray('Linux: curl -fsSL https://ollama.com/install.sh | sh'));
          return;
        }

        console.log(chalk.gray(`Pulling ${model} through Ollama...`));
        const result = spawnSync('ollama', ['pull', model], { stdio: 'inherit' });
        if (result.status !== 0) {
          process.exit(result.status ?? 1);
          return;
        }
      }

      console.log(chalk.green(`✔️ Local model routing set to ollama:${model}`));
      return;
    }

    const configuredProviders = [];
    if (process.env.OPENAI_API_KEY) configuredProviders.push('OpenAI');
    if (process.env.ANTHROPIC_API_KEY) configuredProviders.push('Anthropic');
    if (process.env.GROQ_API_KEY) configuredProviders.push('Groq');

    if (configuredProviders.length === 0) {
      console.log(chalk.yellow('No cloud providers are configured.'));
    } else {
      for (const provider of configuredProviders) {
        console.log(chalk.green(`- ${provider} (Cloud)`));
      }
    }

    const ollamaUrl = process.env.OLLAMA_URL || 'http://127.0.0.1:11434';
    console.log(chalk.gray(`\nLocal model host: ${ollamaUrl}`));
    console.log(chalk.gray('Run `elyan start` to load these providers in the interface.'));
  });

// ----------------------------------------------------------------------------
// COMMAND: status
// ----------------------------------------------------------------------------
program
  .command('status')
  .option('--base-url <url>', 'Base URL for the running Elyan app', 'http://localhost:3000')
  .option('--json', 'Print raw machine-readable dashboard status')
  .description('Shows the local runtime, optional integrations, and optional hosted-control-plane status.')
  .action(async (options) => {
    const baseUrl = options.baseUrl.replace(/\/$/, '');
    const [result, releaseResult] = await Promise.all([
      fetchJson(`${baseUrl}/api/dashboard/status`),
      fetchJson(`${baseUrl}/api/releases/latest`),
    ]);

    if (!result.ok) {
      console.log(chalk.red(`Failed to fetch dashboard status (${result.status}).`));
      process.exit(1);
      return;
    }

    const data = result.data;
    if (options.json) {
      console.log(JSON.stringify(data, null, 2));
      return;
    }

    console.log(chalk.bold.blue('\n📟 Elyan status\n'));
    console.log(`Runtime: ${chalk.green(data.runtime ?? 'local-first')}`);
    console.log(`Models: ${chalk.green(String(data.models?.length ?? 0))}`);
    const searchState = data.readiness?.searchEnabled
      ? data.readiness?.searchAvailable
        ? chalk.green('enabled + reachable')
        : chalk.yellow('enabled but offline')
      : chalk.gray('disabled');
    console.log(`Search: ${searchState}`);
    console.log(`MCP: ${data.mcp?.configured ? chalk.green('configured') : chalk.gray('optional / not configured')}`);
    console.log(`Voice: ${data.readiness?.voiceConfigured ? chalk.green('configured') : chalk.gray('optional')}`);
    console.log(`Local operator: ${data.localAgent?.enabled ? chalk.green('enabled') : chalk.gray('disabled')}`);
    console.log(`Telegram: ${data.channels?.telegram?.enabled ? chalk.green('enabled') : chalk.gray('disabled')}`);
    console.log(`WhatsApp Cloud: ${data.channels?.whatsappCloud?.enabled ? chalk.green('enabled') : chalk.gray('disabled')}`);
    console.log(`iMessage: ${data.channels?.imessage?.enabled ? chalk.green('enabled') : chalk.gray('disabled')}`);
    if (data.controlPlane?.health?.storage) {
      console.log(`Hosted control plane DB: ${chalk.green(String(data.controlPlane.health.storage))}`);
    }
    printLinkedDeviceSnapshot();

    const releaseData = releaseResult.ok ? releaseResult.data : null;
    const currentVersion = packageJson.version;
    const currentTagName = `v${currentVersion}`;
    console.log(`Release: ${chalk.green(currentTagName)} (${currentVersion})`);

    if (releaseData) {
      console.log(`Latest release: ${releaseData.latest?.tagName ? chalk.green(String(releaseData.latest.tagName)) : chalk.gray('none')}`);
      console.log(
        `Update status: ${
          releaseData.updateStatus === 'update_available'
            ? chalk.yellow('update available')
            : releaseData.updateStatus === 'current'
              ? chalk.green('current')
              : chalk.gray('unavailable')
        }`
      );
      console.log(`Update message: ${releaseData.updateMessage ? String(releaseData.updateMessage) : 'No release message available.'}`);
    } else {
      console.log(`Latest release: ${chalk.gray('unavailable')}`);
      console.log(`Update status: ${chalk.gray('unavailable')}`);
      if (releaseResult.status) {
        console.log(`Update message: ${chalk.gray(String(releaseResult.status))}`);
      }
    }

    if (data.surfaces) {
      console.log('\nSurfaces:');
      for (const key of ['local', 'shared', 'hosted']) {
        const surface = data.surfaces[key];
        if (!surface) continue;
        const state = surface.ready ? chalk.green('ready') : chalk.yellow('not ready');
        console.log(`- ${chalk.bold(surface.label)}: ${state}`);
        console.log(`  ${surface.summary}`);
        console.log(`  ${surface.detail}`);
      }
    }

    if (Array.isArray(data.nextSteps) && data.nextSteps.length > 0) {
      console.log('\nNext steps:');
      for (const step of data.nextSteps) {
        console.log(`- ${step}`);
      }
    }
  });

// ----------------------------------------------------------------------------
// COMMAND: open
// ----------------------------------------------------------------------------
program
  .command('open')
  .option('--base-url <url>', 'Base URL for the running Elyan app', 'http://localhost:3000')
  .description('Opens the local Manage UI.')
  .action((options) => {
    const target = `${options.baseUrl.replace(/\/$/, '')}/manage`;
    const opener = process.platform === 'darwin' ? 'open' : process.platform === 'win32' ? 'start' : 'xdg-open';
    const result = spawnSync(opener, [target], {
      stdio: 'ignore',
      shell: process.platform === 'win32',
    });
    if (result.status !== 0) {
      console.log(target);
      return;
    }
    console.log(chalk.green(`Opened ${target}`));
  });

// ----------------------------------------------------------------------------
// COMMAND: service
// ----------------------------------------------------------------------------
program
  .command('service <action>')
  .description('Install or control the local user-level Elyan service.')
  .action((action) => {
    try {
      if (action === 'install') {
        const result = installUserService();
        console.log(chalk.green(`✔️ Installed ${result.platform} service at ${result.path}`));
        console.log(chalk.gray('Run `elyan service start` to start it.'));
        return;
      }

      if (['start', 'stop', 'status'].includes(action)) {
        const result = controlUserService(action);
        if (result.status !== 0) {
          process.exit(result.status ?? 1);
        }
        return;
      }

      console.log(chalk.red('Usage: elyan service install | start | stop | status'));
    } catch (error) {
      console.log(chalk.red(error instanceof Error ? error.message : 'Service command failed'));
      process.exit(1);
    }
  });

// ----------------------------------------------------------------------------
// COMMAND: desktop
// ----------------------------------------------------------------------------
program
  .command('desktop [action] [target]')
  .description('Manage local operator filesystem and terminal permissions.')
  .action((action, target) => {
    const settings = readRuntimeSettingsFile();

    if (!action || action === 'status') {
      console.log(chalk.bold.blue('\n🖥️ Local operator\n'));
      console.log(`Enabled: ${settings.localAgent.enabled ? chalk.green('yes') : chalk.gray('no')}`);
      console.log(`Evidence: ${chalk.green(settings.localAgent.evidenceDir)}`);
      console.log('Allowed roots:');
      for (const root of settings.localAgent.allowedRoots) {
        console.log(`- ${path.resolve(process.cwd(), root)}`);
      }
      console.log(`Protected paths: ${chalk.green(String(settings.localAgent.protectedPaths.length))}`);
      return;
    }

    if (action === 'enable' || action === 'disable') {
      const next = deepClone(settings);
      next.localAgent.enabled = action === 'enable';
      writeRuntimeSettingsFile(next);
      console.log(chalk.green(`✔️ Local operator ${action}d`));
      return;
    }

    if (action === 'grant' && target) {
      const next = deepClone(settings);
      const resolved = path.resolve(process.cwd(), target);
      next.localAgent.enabled = true;
      next.localAgent.allowedRoots = Array.from(new Set([...(next.localAgent.allowedRoots || []), resolved]));
      writeRuntimeSettingsFile(next);
      console.log(chalk.green(`✔️ Granted local operator root: ${resolved}`));
      return;
    }

    if (action === 'revoke' && target) {
      const resolved = path.resolve(process.cwd(), target);
      const next = deepClone(settings);
      next.localAgent.allowedRoots = next.localAgent.allowedRoots.filter((root) => path.resolve(process.cwd(), root) !== resolved);
      writeRuntimeSettingsFile(next);
      console.log(chalk.green(`✔️ Revoked local operator root: ${resolved}`));
      return;
    }

    console.log(chalk.red('Usage: elyan desktop status | enable | disable | grant <path> | revoke <path>'));
  });

// ----------------------------------------------------------------------------
// COMMAND: settings
// ----------------------------------------------------------------------------
program
  .command('settings [action] [path] [value]')
  .description('View or update the local runtime settings JSON used by the dashboard and operator.')
  .action((action, settingsPath, value) => {
    const settings = readRuntimeSettingsFile();

    if (!action || action === 'view') {
      printRuntimeSettingsSummary(settings);
      console.log(JSON.stringify(settings, null, 2));
      return;
    }

    if (action === 'get' && settingsPath) {
      console.log(JSON.stringify(getDeepValue(settings, settingsPath), null, 2));
      return;
    }

    if (action === 'set' && settingsPath) {
      const nextSettings = deepClone(settings);
      setDeepValue(nextSettings, settingsPath, parseLooseValue(value));
      writeRuntimeSettingsFile(nextSettings);
      console.log(chalk.green(`✔️ Updated ${settingsPath} in ${LOCAL_RUNTIME_SETTINGS}`));
      return;
    }

    if (action === 'reset') {
      writeRuntimeSettingsFile(createDefaultRuntimeSettings());
      console.log(chalk.green(`✔️ Reset runtime settings at ${LOCAL_RUNTIME_SETTINGS}`));
      return;
    }

    console.log(chalk.red('Usage: elyan settings view | elyan settings get <path> | elyan settings set <path> <value> | elyan settings reset'));
  });

// ----------------------------------------------------------------------------
// COMMAND: channels
// ----------------------------------------------------------------------------
program
  .command('channels [action] [channel] [field] [value]')
  .description('Inspect or change the channel adapter runtime settings.')
  .action(async (action, channel, field, value) => {
    loadEnvSafe();
    const settings = readRuntimeSettingsFile();

    if (!action || action === 'list') {
      console.log(chalk.bold.blue('\n📡 Channels\n'));
      printChannelStatusLine('telegram', {
        ...settings.channels.telegram,
        configured: Boolean(process.env.TELEGRAM_BOT_TOKEN),
        costProfile: 'free_api',
      });
      printChannelStatusLine('whatsappCloud', {
        ...settings.channels.whatsappCloud,
        configured: Boolean(process.env.WHATSAPP_CLOUD_ACCESS_TOKEN && process.env.WHATSAPP_CLOUD_PHONE_NUMBER_ID && process.env.WHATSAPP_CLOUD_VERIFY_TOKEN),
        costProfile: 'official_api_may_bill_templates',
      });
      printChannelStatusLine('whatsappBaileys', {
        ...settings.channels.whatsappBaileys,
        configured: settings.channels.whatsappBaileys.enabled && fs.existsSync(path.resolve(process.cwd(), settings.channels.whatsappBaileys.sessionPath)),
        costProfile: 'local_unofficial_best_effort',
      });
      printChannelStatusLine('imessage', {
        ...settings.channels.imessage,
        configured: Boolean(process.env.BLUEBUBBLES_SERVER_URL && process.env.BLUEBUBBLES_SERVER_GUID),
        costProfile: 'self_hosted_macos_imessage',
      });
      return;
    }

    if (action === 'doctor') {
      loadEnvSafe();
      console.log(chalk.bold.blue('\n📡 Channel doctor\n'));
      const checks = [
        ['Telegram token', Boolean(process.env.TELEGRAM_BOT_TOKEN)],
        ['WhatsApp Cloud credentials', Boolean(process.env.WHATSAPP_CLOUD_ACCESS_TOKEN && process.env.WHATSAPP_CLOUD_PHONE_NUMBER_ID && process.env.WHATSAPP_CLOUD_VERIFY_TOKEN)],
        ['WhatsApp Cloud app secret', Boolean(process.env.WHATSAPP_CLOUD_APP_SECRET)],
        ['BlueBubbles server', Boolean(process.env.BLUEBUBBLES_SERVER_URL && process.env.BLUEBUBBLES_SERVER_GUID)],
        ['BlueBubbles webhook secret', Boolean(process.env.BLUEBUBBLES_WEBHOOK_SECRET)],
        ['Baileys local session file', fs.existsSync(path.resolve(process.cwd(), settings.channels.whatsappBaileys.sessionPath))],
      ];
      for (const [label, ok] of checks) {
        console.log(`${ok ? chalk.green('ok') : chalk.yellow('missing')} ${label}`);
      }
      console.log(chalk.gray('WhatsApp Cloud can incur Meta template-message costs; Baileys is local best-effort and unofficial.'));
      return;
    }

    if (!channel) {
      console.log(chalk.red('Usage: elyan channels list | doctor | setup <channel> | test <channel> | enable <channel> | disable <channel> | set <channel> <path> <value>'));
      return;
    }

    const nextSettings = deepClone(settings);

    if (action === 'enable') {
      if (!nextSettings.channels[channel]) {
        console.log(chalk.red(`Unknown channel: ${channel}`));
        process.exit(1);
        return;
      }
      nextSettings.channels[channel].enabled = true;
      writeRuntimeSettingsFile(nextSettings);
      console.log(chalk.green(`✔️ Enabled ${channel}`));
      return;
    }

    if (action === 'setup') {
      if (!nextSettings.channels[channel]) {
        console.log(chalk.red(`Unknown channel: ${channel}`));
        process.exit(1);
        return;
      }
      nextSettings.channels[channel].enabled = true;
      if (channel === 'whatsappBaileys') {
        const sessionPath = path.resolve(process.cwd(), nextSettings.channels.whatsappBaileys.sessionPath);
        ensureParentDir(sessionPath);
        if (!fs.existsSync(sessionPath)) {
          atomicWriteFileSync(sessionPath, `${JSON.stringify({
            status: 'pending_pairing',
            updatedAt: new Date().toISOString(),
            note: 'Pairing requires a Baileys runtime worker. This file keeps the local session state explicit.',
          }, null, 2)}\n`);
        }
        console.log(chalk.yellow('WhatsApp Baileys is local and unofficial. Use WhatsApp Cloud for official business-critical delivery.'));
      }
      writeRuntimeSettingsFile(nextSettings);
      console.log(chalk.green(`✔️ Prepared ${channel}`));
      return;
    }

    if (action === 'test') {
      loadEnvSafe();
      if (channel === 'telegram') {
        if (!process.env.TELEGRAM_BOT_TOKEN) {
          console.log(chalk.red('TELEGRAM_BOT_TOKEN is missing.'));
          process.exit(1);
          return;
        }
        const result = await fetchJson(`https://api.telegram.org/bot${process.env.TELEGRAM_BOT_TOKEN}/getMe`);
        console.log(result.ok && result.data?.ok ? chalk.green(`Telegram ok: @${result.data.result.username}`) : chalk.red(`Telegram failed: ${result.status}`));
        if (!result.ok || !result.data?.ok) process.exit(1);
        return;
      }

      if (channel === 'whatsappCloud') {
        if (!process.env.WHATSAPP_CLOUD_ACCESS_TOKEN || !process.env.WHATSAPP_CLOUD_PHONE_NUMBER_ID) {
          console.log(chalk.red('WhatsApp Cloud token or phone number id is missing.'));
          process.exit(1);
          return;
        }
        const apiVersion = process.env.WHATSAPP_CLOUD_API_VERSION || 'v21.0';
        const result = await fetchJson(`https://graph.facebook.com/${apiVersion}/${process.env.WHATSAPP_CLOUD_PHONE_NUMBER_ID}`, 5000, {
          headers: { Authorization: `Bearer ${process.env.WHATSAPP_CLOUD_ACCESS_TOKEN}` },
        });
        console.log(result.ok ? chalk.green('WhatsApp Cloud credentials are reachable.') : chalk.red(`WhatsApp Cloud failed: ${result.status}`));
        if (!result.ok) process.exit(1);
        return;
      }

      if (channel === 'imessage') {
        if (!process.env.BLUEBUBBLES_SERVER_URL) {
          console.log(chalk.red('BLUEBUBBLES_SERVER_URL is missing.'));
          process.exit(1);
          return;
        }
        const result = await fetchJson(process.env.BLUEBUBBLES_SERVER_URL, 5000, {
          headers: process.env.BLUEBUBBLES_SERVER_GUID ? { Authorization: `Bearer ${process.env.BLUEBUBBLES_SERVER_GUID}` } : {},
        });
        console.log(result.ok ? chalk.green('BlueBubbles server is reachable.') : chalk.red(`BlueBubbles failed: ${result.status}`));
        if (!result.ok) process.exit(1);
        return;
      }

      if (channel === 'whatsappBaileys') {
        const sessionPath = path.resolve(process.cwd(), settings.channels.whatsappBaileys.sessionPath);
        const exists = fs.existsSync(sessionPath);
        console.log(exists ? chalk.yellow(`Baileys session exists: ${sessionPath}`) : chalk.red(`Baileys session missing: ${sessionPath}`));
        console.log(chalk.gray('Baileys is local best-effort and unofficial; pairing state is kept on disk.'));
        if (!exists) process.exit(1);
        return;
      }
    }

    if (action === 'disable') {
      if (!nextSettings.channels[channel]) {
        console.log(chalk.red(`Unknown channel: ${channel}`));
        process.exit(1);
        return;
      }
      nextSettings.channels[channel].enabled = false;
      writeRuntimeSettingsFile(nextSettings);
      console.log(chalk.green(`✔️ Disabled ${channel}`));
      return;
    }

    if (action === 'set' && field && value !== undefined) {
      if (!nextSettings.channels[channel]) {
        console.log(chalk.red(`Unknown channel: ${channel}`));
        process.exit(1);
        return;
      }
      setDeepValue(nextSettings.channels[channel], field, parseLooseValue(value));
      writeRuntimeSettingsFile(nextSettings);
      console.log(chalk.green(`✔️ Updated channels.${channel}.${field}`));
      return;
    }

    console.log(chalk.red('Usage: elyan channels list | doctor | setup <channel> | test <channel> | enable <channel> | disable <channel> | set <channel> <field> <value>'));
  });

// ----------------------------------------------------------------------------
// COMMAND: mcp
// ----------------------------------------------------------------------------
program
  .command('mcp [action] [server] [tool]')
  .description('Inspect or update MCP server connections in the runtime settings.')
  .action((action, server, tool) => {
    loadEnvSafe();
    const settings = readRuntimeSettingsFile();

    if (!action || action === 'list') {
      console.log(chalk.bold.blue('\n🔌 MCP servers\n'));
      if (settings.mcp.servers.length === 0) {
        console.log(chalk.gray('No MCP servers configured.'));
        return;
      }

      for (const server of settings.mcp.servers) {
        console.log(`- ${chalk.bold(server.id)} (${server.transport}) ${server.enabled ? chalk.green('enabled') : chalk.gray('disabled')}`);
        if (server.transport === 'streamable-http') {
          console.log(`  URL: ${server.url}`);
        } else {
          console.log(`  Command: ${server.command}`);
        }
      }
      return;
    }

    if (action === 'doctor') {
      const doctor = buildMcpDoctor(settings, process.env);
      console.log(chalk.bold.blue('\n🔎 MCP doctor\n'));
      console.log(`Configured servers: ${doctor.configured ? chalk.green(String(doctor.serverCount)) : chalk.gray('0')}`);
      console.log(`Disabled by env: ${doctor.disabledServerIds.size > 0 ? chalk.yellow(Array.from(doctor.disabledServerIds).join(', ')) : chalk.gray('none')}`);
      console.log(`Disabled tools by env: ${doctor.disabledToolNames.size > 0 ? chalk.yellow(Array.from(doctor.disabledToolNames).join(', ')) : chalk.gray('none')}`);

      if (doctor.servers.length === 0) {
        console.log(chalk.gray('No MCP servers configured. Set ELYAN_MCP_SERVERS or use elyan mcp set <json>.'));
        return;
      }

      for (const item of doctor.servers) {
        const badge = item.enabled ? chalk.green(item.state) : chalk.gray(item.state);
        console.log(`- ${chalk.bold(item.id)} (${item.transport}) ${badge}`);
        console.log(`  ${item.stateReason}`);
        console.log(`  Endpoint: ${chalk.gray(item.endpoint || 'n/a')}`);
        console.log(`  Disabled tools: ${item.disabledToolNames.length > 0 ? chalk.yellow(item.disabledToolNames.join(', ')) : chalk.gray('none')}`);
      }
      return;
    }

    if (action === 'set' && server) {
      try {
        const nextSettings = setMcpServers(settings, server);
        writeRuntimeSettingsFile(nextSettings);
        console.log(chalk.green(`✔️ Updated MCP servers in ${LOCAL_RUNTIME_SETTINGS}`));
      } catch (error) {
        console.log(chalk.red(`Invalid MCP JSON: ${error instanceof Error ? error.message : 'parse failure'}`));
        process.exit(1);
      }
      return;
    }

    if ((action === 'enable' || action === 'disable') && server) {
      try {
        const nextSettings = setMcpServerEnabled(settings, server, action === 'enable');
        writeRuntimeSettingsFile(nextSettings);
        console.log(chalk.green(`✔️ ${action === 'enable' ? 'Enabled' : 'Disabled'} MCP server ${server}`));
      } catch (error) {
        console.log(chalk.red(error instanceof Error ? error.message : 'Failed to update MCP server.'));
        process.exit(1);
      }
      return;
    }

    if (action === 'disable-tool' && server && tool) {
      try {
        const nextSettings = disableMcpTool(settings, server, tool);
        writeRuntimeSettingsFile(nextSettings);
        console.log(chalk.green(`✔️ Disabled MCP tool ${server}:${tool}`));
      } catch (error) {
        console.log(chalk.red(error instanceof Error ? error.message : 'Failed to disable MCP tool.'));
        process.exit(1);
      }
      return;
    }

    console.log(chalk.red('Usage: elyan mcp list | doctor | set <json> | enable <server> | disable <server> | disable-tool <server> <tool>'));
  });

// ----------------------------------------------------------------------------
// COMMAND: voice
// ----------------------------------------------------------------------------
program
  .command('voice [action] [key] [value]')
  .description('Inspect or update the local voice settings used by the browser wake-word path.')
  .action((action, key, value) => {
    loadEnvSafe();
    const settings = readRuntimeSettingsFile();

    if (!action || action === 'status') {
      console.log(chalk.bold.blue('\n🎙️ Voice\n'));
      console.log(`Enabled: ${settings.voice.enabled ? chalk.green('yes') : chalk.gray('no')}`);
      console.log(`Wake word: ${chalk.green(settings.voice.wakeWord || 'elyan')}`);
      console.log(`Access key: ${process.env.PICOVOICE_ACCESS_KEY ? chalk.green('configured') : chalk.gray('missing')}`);
      console.log(`Open dashboard: ${chalk.gray('http://localhost:3000/manage')}`);
      return;
    }

    if (action === 'enable' || action === 'disable') {
      const nextSettings = deepClone(settings);
      nextSettings.voice.enabled = action === 'enable';
      writeRuntimeSettingsFile(nextSettings);
      console.log(chalk.green(`✔️ Voice ${action}d`));
      return;
    }

    if (action === 'set' && key && value !== undefined) {
      const nextSettings = deepClone(settings);
      setDeepValue(nextSettings.voice, key, parseLooseValue(value));
      writeRuntimeSettingsFile(nextSettings);
      console.log(chalk.green(`✔️ Updated voice.${key}`));
      return;
    }

    console.log(chalk.red('Usage: elyan voice status | enable | disable | set <field> <value>'));
  });

// ----------------------------------------------------------------------------
// COMMAND: start
// ----------------------------------------------------------------------------
program
  .command('start')
  .description('Builds and runs the direct local Node.js runtime from the package root.')
  .action(() => {
    console.log(chalk.blue('🚀 Building Elyan for the direct local runtime...'));
    const root = path.join(__dirname, '..');
    const npmBin = /^win/.test(process.platform) ? 'npm.cmd' : 'npm';
    const build = spawn(npmBin, ['run', 'build'], { stdio: 'inherit', cwd: root });

    build.on('close', (code) => {
      if (code !== 0) {
        process.exit(code ?? 1);
        return;
      }

      console.log(chalk.blue('🚀 Starting Elyan local runtime...'));
      const start = spawn(npmBin, ['run', 'start'], { stdio: 'inherit', cwd: root });
      start.on('close', (startCode) => {
        process.exit(startCode ?? 0);
      });
    });
  });

// ----------------------------------------------------------------------------
// COMMAND: dev
// ----------------------------------------------------------------------------
program
  .command('dev')
  .description('Runs the local Next.js development server from the package root.')
  .action(() => {
    console.log(chalk.yellow('⚙️ Starting local development environment...'));
    spawn(/^win/.test(process.platform) ? 'npm.cmd' : 'npm', ['run', 'dev'], { stdio: 'inherit', cwd: path.join(__dirname, '..') });
  });

program.parse(process.argv);
