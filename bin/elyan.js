#!/usr/bin/env node
/*
 * Elyan başlatıcısı — `npm install -g elyan` sonrası tek komut: `elyan`.
 *
 * İlk çalıştırmada ~/.elyan/venv altında Python ortamını kendisi kurar
 * (çekirdek paketler ~1 dk; ağır paketler arka planda devam eder), sonra
 * Python CLI'ına devreder. Kullanıcının tek yapması gereken `elyan` yazmak.
 */
'use strict';

const { spawnSync, spawn } = require('child_process');
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

function findSystemPython() {
  const candidates = IS_WIN ? ['py', 'python', 'python3'] : ['python3', 'python'];
  for (const cmd of candidates) {
    const args = cmd === 'py' ? ['-3', '--version'] : ['--version'];
    const res = spawnSync(cmd, args, { encoding: 'utf8' });
    if (res.status !== 0) continue;
    const match = String(res.stdout || res.stderr).match(/Python (\d+)\.(\d+)/);
    if (!match) continue;
    const [major, minor] = [Number(match[1]), Number(match[2])];
    if (major > 3 || (major === 3 && minor >= 10)) {
      return cmd === 'py' ? { cmd: 'py', prefix: ['-3'] } : { cmd, prefix: [] };
    }
  }
  return null;
}

function run(cmd, args, opts = {}) {
  const res = spawnSync(cmd, args, { stdio: 'inherit', ...opts });
  return res.status === 0;
}

function bootstrap() {
  console.log('Elyan ilk kez çalışıyor — kurulum yapılıyor (tek seferlik, ~1 dk)…');
  const py = findSystemPython();
  if (!py) {
    console.error('');
    console.error('Python 3.10+ bulunamadı. Kur ve tekrar `elyan` yaz:');
    console.error(IS_WIN
      ? '  https://python.org/downloads  (kurulumda "Add to PATH" işaretle)'
      : process.platform === 'darwin'
        ? '  brew install python3   (veya https://python.org/downloads)'
        : '  sudo apt install python3 python3-venv   (veya dağıtımının paketi)');
    process.exit(1);
  }

  fs.mkdirSync(ELYAN_HOME, { recursive: true });
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
  fs.writeFileSync(READY_MARKER, new Date().toISOString() + '\n');

  // Ağır paketler arka planda — kullanıcıyı bekletme.
  const extrasLog = fs.openSync(path.join(ELYAN_HOME, 'extras.log'), 'a');
  const child = spawn(VENV_PY, [path.join(ROOT, 'scripts', 'install_extras.py')], {
    cwd: ROOT,
    detached: true,
    stdio: ['ignore', extrasLog, extrasLog],
  });
  child.unref();
  console.log('• Ek yetenek paketleri arka planda kuruluyor (seni beklemez).');
  console.log('Kurulum tamam ✓');
  console.log('');
}

if (!fs.existsSync(READY_MARKER) || !fs.existsSync(VENV_PY)) {
  bootstrap();
}

const result = spawnSync(VENV_PY, ['-m', 'cli', ...process.argv.slice(2)], {
  cwd: ROOT,
  stdio: 'inherit',
});
process.exit(result.status === null ? 1 : result.status);
