#!/usr/bin/env node
/* eslint-disable @typescript-eslint/no-require-imports */

const { execFileSync } = require('child_process');
const fs = require('fs');
const path = require('path');

const ROOT = path.resolve(__dirname, '..');
const RELEASE_WORKFLOW = path.join(ROOT, '.github', 'workflows', 'release.yml');

const REQUIRED_RELEASE_ASSETS = [
  'elyan-macos-arm64.zip',
  'elyan-macos-x64.zip',
  'elyan-linux-x64.tar.gz',
  'elyan-windows-x64.zip',
];

function validateReleaseWorkflow(workflowText) {
  const missing = REQUIRED_RELEASE_ASSETS.filter((assetName) => !workflowText.includes(`release-assets/${assetName}`));

  return {
    ok: missing.length === 0,
    missing,
  };
}

function run(command, args) {
  console.log(`\n> ${command} ${args.join(' ')}`);
  execFileSync(command, args, {
    cwd: ROOT,
    stdio: 'inherit',
  });
}

function main() {
  const packageJson = JSON.parse(fs.readFileSync(path.join(ROOT, 'package.json'), 'utf8'));
  const workflowText = fs.readFileSync(RELEASE_WORKFLOW, 'utf8');
  const workflowValidation = validateReleaseWorkflow(workflowText);

  if (!workflowValidation.ok) {
    console.error(`Missing required release assets: ${workflowValidation.missing.join(', ')}`);
    process.exit(1);
  }

  console.log(`Elyan release check for v${packageJson.version}`);
  console.log(`Repository: ${packageJson.repository?.url ?? 'unknown'}`);
  console.log(`Required assets: ${REQUIRED_RELEASE_ASSETS.join(', ')}`);

  run('npm', ['run', 'security:check']);
  run('npm', ['run', 'lint']);
  run('npm', ['run', 'test']);
  run('npm', ['run', 'build']);
  run('npm', ['pack', '--dry-run']);

  console.log('\nRelease check passed.');
}

if (require.main === module) {
  main();
}

module.exports = {
  REQUIRED_RELEASE_ASSETS,
  validateReleaseWorkflow,
};
