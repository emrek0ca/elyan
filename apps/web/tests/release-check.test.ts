import { createRequire } from 'module';
import { readFileSync } from 'fs';
import { join } from 'path';
import { describe, expect, it } from 'vitest';

const require = createRequire(import.meta.url);
const {
  REQUIRED_RELEASE_ASSETS,
  REQUIRED_ML_FILES,
  RELEASE_WORKFLOW,
  validateReleaseWorkflow,
}: {
  REQUIRED_RELEASE_ASSETS: string[];
  REQUIRED_ML_FILES: string[];
  RELEASE_WORKFLOW: string;
  validateReleaseWorkflow: (workflowText: string) => { ok: boolean; missing: string[] };
} = require('../scripts/release-check.js');

describe('release readiness check', () => {
  const repoRoot = join(process.cwd(), '..', '..');

  it('keeps the v1.3 release asset matrix exact', () => {
    expect(REQUIRED_RELEASE_ASSETS).toEqual([
      'elyan-macos-arm64.zip',
      'elyan-macos-x64.zip',
      'elyan-linux-x64.tar.gz',
      'elyan-windows-x64.zip',
    ]);
  });

  it('includes the learning and retrieval surface in the release gate', () => {
    expect(REQUIRED_ML_FILES).toEqual(
      expect.arrayContaining([
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
      ])
    );
  });

  it('validates the GitHub release workflow publishes every required asset', () => {
    const workflowText = readFileSync(join(repoRoot, '.github', 'workflows', 'release.yml'), 'utf8');
    expect(RELEASE_WORKFLOW).toBe(join(repoRoot, '.github', 'workflows', 'release.yml'));
    expect(validateReleaseWorkflow(workflowText)).toEqual({ ok: true, missing: [] });
  });

  it('fails closed when a required release artifact is missing', () => {
    expect(validateReleaseWorkflow('release-assets/elyan-linux-x64.tar.gz')).toEqual({
      ok: false,
      missing: ['elyan-macos-arm64.zip', 'elyan-macos-x64.zip', 'elyan-windows-x64.zip'],
    });
  });
});
