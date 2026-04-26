const { spawn, spawnSync } = require('child_process');
const fs = require('fs');
const path = require('path');

function commandExists(command) {
  const result = spawnSync(command, ['--version'], {
    stdio: 'ignore',
    shell: /^win/.test(process.platform),
  });

  return !result.error && result.status === 0;
}

function runCommand(command, args, cwd) {
  return new Promise((resolve, reject) => {
    const child = spawn(command, args, {
      stdio: 'inherit',
      cwd,
      shell: /^win/.test(process.platform),
    });

    child.on('error', reject);
    child.on('close', (code) => {
      if (code === 0) {
        resolve();
        return;
      }

      reject(new Error(`${command} ${args.join(' ')} exited with code ${code ?? 1}`));
    });
  });
}

function isSourceCheckout(cliDir) {
  return fs.existsSync(path.join(cliDir, '..', '.git'));
}

function isHomebrewInstall() {
  return Boolean(process.env.HOMEBREW_PREFIX) || /[\\/]Cellar[\\/]/.test(process.execPath);
}

module.exports = {
  commandExists,
  isHomebrewInstall,
  isSourceCheckout,
  runCommand,
};
