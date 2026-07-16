#!/usr/bin/env node
/*
 * Elyan başlatıcısı — `npm install -g elyan` sonrası tek komut: `elyan`.
 *
 * İlk çalıştırmada ~/.elyan/venv altında Python ortamını kendisi kurar,
 * yetenek paketlerini tamamlar ve sonra Python CLI'ına devreder.
 */
'use strict';

const { spawnSync } = require('child_process');
const fs = require('fs');
const os = require('os');
const path = require('path');

const ROOT = path.resolve(__dirname, '..');
const ELYAN_HOME = path.join(os.homedir(), '.elyan');
const VENV = path.join(ELYAN_HOME, 'venv');
const IS_WIN = process.platform === 'win32';
const VENV_PY = IS_WIN
  ? path.join(VENV, 'Scripts', 'python.exe')
  : path.join(VENV, 'bin', 'python3');
const READY_MARKER = path.join(ELYAN_HOME, '.core-ready');
const PACKAGE_VERSION = String(require(path.join(ROOT, 'package.json')).version || '0.0.0');
const REQUIRED_CORE_MODULES = [
  'requests',
  'httpx',
  'websocket',
  'psutil',
  'PIL',
  'openpyxl',
  'litellm',
  'langgraph',
  'google.genai',
];

function findSystemPython() {
  const candidates = IS_WIN
    ? [
        { cmd: 'py', prefix: ['-3.13'] },
        { cmd: 'py', prefix: ['-3.12'] },
        { cmd: 'py', prefix: ['-3.11'] },
        { cmd: 'py', prefix: ['-3.10'] },
        { cmd: 'python', prefix: [] },
        { cmd: 'python3', prefix: [] },
      ]
    : [
        { cmd: 'python3.13', prefix: [] },
        { cmd: 'python3.12', prefix: [] },
        { cmd: 'python3.11', prefix: [] },
        { cmd: 'python3.10', prefix: [] },
        { cmd: 'python3', prefix: [] },
        { cmd: 'python', prefix: [] },
      ];
  for (const candidate of candidates) {
    const res = spawnSync(candidate.cmd, [...candidate.prefix, '--version'], { encoding: 'utf8' });
    if (res.status !== 0) continue;
    const match = String(res.stdout || res.stderr).match(/Python (\d+)\.(\d+)/);
    if (!match) continue;
    const [major, minor] = [Number(match[1]), Number(match[2])];
    if (major === 3 && minor >= 10 && minor < 14) {
      return candidate;
    }
  }
  return null;
}

function supportedPython(pythonPath) {
  if (!fs.existsSync(pythonPath)) return false;
  const probe = spawnSync(
    pythonPath,
    ['-c', 'import sys; raise SystemExit(0 if (3, 10) <= sys.version_info[:2] < (3, 14) else 1)'],
    { cwd: ROOT, stdio: 'ignore' },
  );
  return probe.status === 0;
}

function run(cmd, args, opts = {}) {
  const res = spawnSync(cmd, args, { stdio: 'inherit', ...opts });
  return res.status === 0;
}

function coreReady() {
  if (!supportedPython(VENV_PY) || !fs.existsSync(READY_MARKER)) return false;
  try {
    const marker = JSON.parse(fs.readFileSync(READY_MARKER, 'utf8'));
    if (String(marker.version || '') !== PACKAGE_VERSION) return false;
  } catch (_) {
    return false;
  }
  const probe = spawnSync(
    VENV_PY,
    [
      '-c',
      `from importlib.util import find_spec; import sys; sys.exit(any(find_spec(name) is None for name in ${JSON.stringify(REQUIRED_CORE_MODULES)}))`,
    ],
    { cwd: ROOT, stdio: 'ignore' },
  );
  return probe.status === 0;
}

function daemonRunning() {
  if (!fs.existsSync(VENV_PY)) return false;
  const probe = spawnSync(
    VENV_PY,
    ['-c', 'from runtime.daemon import read_daemon_pid; print(read_daemon_pid())'],
    { cwd: ROOT, encoding: 'utf8' },
  );
  return probe.status === 0 && Number(String(probe.stdout || '').trim()) > 0;
}

function bootstrap({ recreateVenv = false } = {}) {
  console.log('Elyan veri ortamı hazırlanıyor (ilk kurulum veya sürüm güncellemesi)…');
  const py = findSystemPython();
  if (!py) {
    console.error('');
    console.error('Uyumlu Python 3.10–3.13 bulunamadı. Kur ve tekrar `elyan` yaz:');
    console.error(IS_WIN
      ? '  https://python.org/downloads  (kurulumda "Add to PATH" işaretle)'
      : process.platform === 'darwin'
        ? '  brew install python3   (veya https://python.org/downloads)'
        : '  sudo apt install python3 python3-venv   (veya dağıtımının paketi)');
    process.exit(1);
  }

  fs.mkdirSync(ELYAN_HOME, { recursive: true });
  if (recreateVenv && fs.existsSync(VENV)) {
    console.log('• Uyumsuz Python ortamı yenileniyor…');
    fs.rmSync(VENV, { recursive: true, force: true });
  }
  if (!fs.existsSync(VENV_PY)) {
    console.log('• Python ortamı hazırlanıyor…');
    if (!run(py.cmd, [...py.prefix, '-m', 'venv', VENV])) {
      console.error('venv oluşturulamadı. Linux ise: sudo apt install python3-venv');
      process.exit(1);
    }
  }

  console.log('• Çekirdek paketler kuruluyor…');
  run(VENV_PY, ['-m', 'pip', 'install', '--quiet', '--upgrade', 'pip']);
  const coreReq = path.join(ROOT, 'requirements-core.txt');
  if (!run(VENV_PY, ['-m', 'pip', 'install', '--quiet', '-r', coreReq])) {
    console.error('Paket kurulumu başarısız. İnterneti kontrol edip tekrar `elyan` yaz.');
    process.exit(1);
  }
  console.log('• Ek yetenek paketleri doğrulanıyor…');
  const extrasReady = run(VENV_PY, [path.join(ROOT, 'scripts', 'install_extras.py')], { cwd: ROOT });
  if (!extrasReady) {
    console.warn('• Bazı opsiyonel yetenekler kurulamadı; ayrıntı için `elyan doctor` çalıştır.');
  }
  fs.writeFileSync(READY_MARKER, JSON.stringify({
    version: PACKAGE_VERSION,
    installedAt: new Date().toISOString(),
    optionalCapabilitiesReady: extrasReady,
  }) + '\n');

  console.log('Kurulum tamam ✓');
  console.log('');
}

const shouldRepair = !coreReady();
const shouldReplaceVenv = fs.existsSync(VENV_PY) && !supportedPython(VENV_PY);
const shouldRestartDaemon = shouldRepair && daemonRunning();
if (shouldRepair) {
  if (shouldRestartDaemon && !run(VENV_PY, ['-m', 'cli', 'stop'], { cwd: ROOT })) {
    console.error('Çalışan masaüstü motoru güvenli şekilde durdurulamadı; güncelleme uygulanmadı.');
    process.exit(1);
  }
  bootstrap({ recreateVenv: shouldReplaceVenv });
}

if (shouldRestartDaemon) {
  console.log('• Çalışan masaüstü motoru güncel veri ortamıyla yeniden başlatılıyor…');
  if (!run(VENV_PY, ['-m', 'cli', 'restart'], { cwd: ROOT })) {
    try { fs.unlinkSync(READY_MARKER); } catch (_) {}
    console.error('Masaüstü motoru yeniden başlatılamadı. `elyan restart` ile tekrar dene.');
    process.exit(1);
  }
}

const result = spawnSync(VENV_PY, ['-m', 'cli', ...process.argv.slice(2)], {
  cwd: ROOT,
  stdio: 'inherit',
});
process.exit(result.status === null ? 1 : result.status);
