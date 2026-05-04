import { execFileSync } from 'child_process';
import { mkdtemp, mkdir, rm, writeFile } from 'fs/promises';
import { tmpdir } from 'os';
import path from 'path';
import { afterEach, describe, expect, it } from 'vitest';
import { captureRepositorySnapshot } from '@/core/orchestration/repo-inspection';

const tempDirs: string[] = [];

async function createTempDir() {
  const dir = await mkdtemp(path.join(tmpdir(), 'elyan-repo-inspection-'));
  tempDirs.push(dir);
  return dir;
}

afterEach(async () => {
  while (tempDirs.length > 0) {
    await rm(tempDirs.pop()!, { recursive: true, force: true });
  }
});

describe('repository inspection snapshots', () => {
  it('uses repo libraries to read git, file, diff, and TypeScript signals', async () => {
    const root = await createTempDir();
    const srcDir = path.join(root, 'src');
    await mkdir(srcDir, { recursive: true });

    await writeFile(
      path.join(root, 'package.json'),
      JSON.stringify(
        {
          name: 'repo-inspection-fixture',
          private: true,
          type: 'module',
        },
        null,
        2
      ),
      'utf8'
    );
    await writeFile(
      path.join(srcDir, 'main.ts'),
      [
        'export function hello(name: string) {',
        '  return `hello ${name}`;',
        '}',
        '',
      ].join('\n'),
      'utf8'
    );
    await writeFile(
      path.join(srcDir, 'entry.tsx'),
      [
        'export const App = () => <main>App</main>;',
        '',
      ].join('\n'),
      'utf8'
    );

    execFileSync('git', ['init'], { cwd: root, stdio: 'ignore' });
    execFileSync('git', ['config', 'user.email', 'test@example.com'], { cwd: root, stdio: 'ignore' });
    execFileSync('git', ['config', 'user.name', 'Test User'], { cwd: root, stdio: 'ignore' });
    execFileSync('git', ['add', '.'], { cwd: root, stdio: 'ignore' });
    execFileSync('git', ['commit', '-m', 'init'], { cwd: root, stdio: 'ignore' });

    await writeFile(
      path.join(srcDir, 'main.ts'),
      [
        'export function hello(name: string) {',
        '  return `hello ${name}!`;',
        '}',
        '',
      ].join('\n'),
      'utf8'
    );

    const snapshot = await captureRepositorySnapshot(root);

    expect(snapshot.repoInspected).toBe(true);
    expect(snapshot.repoBranch).not.toBe('');
    expect(snapshot.repoDirtyFileCount).toBeGreaterThan(0);
    expect(snapshot.repoDirtySummary).toContain('src/main.ts');
    expect(snapshot.repoChangedFiles).toContain('src/main.ts');
    expect(snapshot.repoEntrypoints).toEqual(expect.arrayContaining(['src/main.ts']));
    expect(snapshot.repoTypeScriptFileCount).toBeGreaterThanOrEqual(2);
    expect(snapshot.repoExportedSymbolCount).toBeGreaterThan(0);
    expect(snapshot.repoPatchSummary).toContain('src/main.ts');
  });
});
