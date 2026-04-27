import { createRequire } from 'module';
import { readFileSync } from 'fs';
import { join } from 'path';
import { describe, expect, it } from 'vitest';

const require = createRequire(import.meta.url);
const {
  REQUIRED_RELEASE_ASSETS,
  validateReleaseWorkflow,
}: {
  REQUIRED_RELEASE_ASSETS: string[];
  validateReleaseWorkflow: (workflowText: string) => { ok: boolean; missing: string[] };
} = require('../scripts/release-check.js');

describe('release readiness check', () => {
  it('keeps the v1.3 release asset matrix exact', () => {
    expect(REQUIRED_RELEASE_ASSETS).toEqual([
      'elyan-macos-arm64.zip',
      'elyan-macos-x64.zip',
      'elyan-linux-x64.tar.gz',
      'elyan-windows-x64.zip',
    ]);
  });

  it('validates the GitHub release workflow publishes every required asset', () => {
    const workflowText = readFileSync(join(process.cwd(), '.github', 'workflows', 'release.yml'), 'utf8');
    expect(validateReleaseWorkflow(workflowText)).toEqual({ ok: true, missing: [] });
  });

  it('fails closed when a required release artifact is missing', () => {
    expect(validateReleaseWorkflow('release-assets/elyan-linux-x64.tar.gz')).toEqual({
      ok: false,
      missing: ['elyan-macos-arm64.zip', 'elyan-macos-x64.zip', 'elyan-windows-x64.zip'],
    });
  });
});
