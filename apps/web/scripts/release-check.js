#!/usr/bin/env node
/* eslint-disable @typescript-eslint/no-require-imports */

const { execFileSync } = require('child_process');
const fs = require('fs');
const path = require('path');

const ROOT = path.resolve(__dirname, '..');
const REPO_ROOT = path.resolve(ROOT, '..', '..');
const RELEASE_WORKFLOW = path.join(REPO_ROOT, '.github', 'workflows', 'release.yml');

const REQUIRED_RELEASE_ASSETS = [
  'elyan-macos-arm64.zip',
  'elyan-macos-x64.zip',
  'elyan-linux-x64.tar.gz',
  'elyan-windows-x64.zip',
];

const REQUIRED_ML_FILES = [
  'scripts/ml-bootstrap.ts',
  'scripts/ml-worker.ts',
  'scripts/ml-train.py',
  'release/systemd/elyan-ml.service.example',
  'src/core/ml/index.ts',
  'src/core/ml/bootstrap.ts',
  'src/core/ml/model-routing.ts',
  'src/core/retrieval/embeddings.ts',
  'src/core/retrieval/context.ts',
  'src/core/retrieval/vector-store.ts',
  'src/core/retrieval/index.ts',
  'src/core/retrieval/web.ts',
  'src/core/memory/index.ts',
  'src/core/reasoning/index.ts',
  'src/core/reasoning/engine.ts',
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
  const missingMlFiles = REQUIRED_ML_FILES.filter((relativePath) => !fs.existsSync(path.join(ROOT, relativePath)));

  if (!workflowValidation.ok) {
    console.error(`Missing required release assets: ${workflowValidation.missing.join(', ')}`);
    process.exit(1);
  }

  if (missingMlFiles.length > 0) {
    console.error(`Missing required ML release files: ${missingMlFiles.join(', ')}`);
    process.exit(1);
  }

  console.log(`Elyan release check for v${packageJson.version}`);
  console.log(`Repository: ${packageJson.repository?.url ?? 'unknown'}`);
  console.log(`Required assets: ${REQUIRED_RELEASE_ASSETS.join(', ')}`);
  console.log(`ML files: ${REQUIRED_ML_FILES.join(', ')}`);

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
  REQUIRED_ML_FILES,
  RELEASE_WORKFLOW,
  validateReleaseWorkflow,
};
