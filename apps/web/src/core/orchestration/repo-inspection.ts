import { readFile } from 'fs/promises';
import path from 'path';
import { diffLines } from 'diff';
import fg from 'fast-glob';
import simpleGit from 'simple-git';
import { Project } from 'ts-morph';

type RepositoryInspectionSnapshot = {
  repoInspected: boolean;
  repoBranch: string;
  repoDirtyFileCount: number;
  repoDirtySummary: string;
  repoChangedFiles: string[];
  repoEntrypoints: string[];
  repoTypeScriptFileCount: number;
  repoExportedSymbolCount: number;
  repoPatchSummary: string;
  repoWorkspaceFileCount: number;
  repoInspectionError?: string;
  checksPassed: boolean;
};

const SOURCE_GLOB = [
  '**/*.{ts,tsx,js,jsx,json,md,yaml,yml}',
  '!**/node_modules/**',
  '!**/.git/**',
  '!**/.next/**',
  '!**/dist/**',
  '!**/coverage/**',
];

const ENTRYPOINT_PATTERN = /(?:^|\/)(?:app\/page|pages\/index|src\/main|src\/index|main|index)\.(?:ts|tsx|js|jsx)$/i;

function unique(items: string[]) {
  return [...new Set(items.map((item) => item.trim()).filter(Boolean))];
}

function summarizeDirtyFiles(files: Array<{ path: string; index: string; working_dir: string }>) {
  if (files.length === 0) {
    return 'clean';
  }

  return files
    .slice(0, 12)
    .map((file) => `${file.path}:${file.index || ' '}/${file.working_dir || ' '}`)
    .join(', ');
}

function summarizePatchLines(root: string, filePath: string, before: string, after: string) {
  const hunks = diffLines(before, after);
  const added = hunks.reduce((count, part) => count + (part.added ? part.count ?? 0 : 0), 0);
  const removed = hunks.reduce((count, part) => count + (part.removed ? part.count ?? 0 : 0), 0);

  if (added === 0 && removed === 0) {
    return '';
  }

  const relPath = path.relative(root, filePath).replaceAll(path.sep, '/');
  return `${relPath}: +${added} / -${removed} lines`;
}

async function analyzeTypeScriptFiles(root: string, sourceFiles: string[]) {
  const tsFiles = sourceFiles.filter((file) => /\.(ts|tsx)$/i.test(file));
  if (tsFiles.length === 0) {
    return {
      repoTypeScriptFileCount: 0,
      repoExportedSymbolCount: 0,
      repoEntrypoints: [] as string[],
    };
  }

  const project = new Project({
    skipAddingFilesFromTsConfig: true,
    skipFileDependencyResolution: true,
    useInMemoryFileSystem: false,
  });

  const analysisFiles = tsFiles.slice(0, 80).map((file) => path.join(root, file));
  project.addSourceFilesAtPaths(analysisFiles);

  let exportedSymbolCount = 0;
  for (const sourceFile of project.getSourceFiles()) {
    exportedSymbolCount += sourceFile.getExportedDeclarations().size;
  }

  const repoEntrypoints = tsFiles.filter((file) => ENTRYPOINT_PATTERN.test(file)).slice(0, 8);

  return {
    repoTypeScriptFileCount: tsFiles.length,
    repoExportedSymbolCount: exportedSymbolCount,
    repoEntrypoints,
  };
}

async function buildPatchSummary(root: string, git: ReturnType<typeof simpleGit>, changedFiles: string[]) {
  const candidate = changedFiles.find((file) => /\.(ts|tsx|js|jsx|json|md|yaml|yml)$/i.test(file));
  if (!candidate) {
    return '';
  }

  const filePath = path.join(root, candidate);
  try {
    const [current, previous] = await Promise.all([
      readFile(filePath, 'utf8').catch(() => ''),
      git.show([`HEAD:${candidate}`]).catch(() => ''),
    ]);

    return summarizePatchLines(root, filePath, previous, current);
  } catch {
    return '';
  }
}

export async function captureRepositorySnapshot(root = process.cwd()): Promise<RepositoryInspectionSnapshot> {
  const projectRoot = path.resolve(root);
  const git = simpleGit({ baseDir: projectRoot, binary: 'git' });

  try {
    const [status, workspaceFiles] = await Promise.all([
      git.status(),
      fg(SOURCE_GLOB, {
        cwd: projectRoot,
        dot: true,
        onlyFiles: true,
        unique: true,
        followSymbolicLinks: false,
        suppressErrors: true,
      }),
    ]);

    const changedFiles = unique(status.files.map((file) => file.path));
    const typeScriptSummary = await analyzeTypeScriptFiles(projectRoot, workspaceFiles);
    const repoPatchSummary = await buildPatchSummary(projectRoot, git, changedFiles);

    return {
      repoInspected: true,
      repoBranch: status.current || 'unknown',
      repoDirtyFileCount: changedFiles.length,
      repoDirtySummary: summarizeDirtyFiles(status.files),
      repoChangedFiles: changedFiles.slice(0, 20),
      repoEntrypoints: typeScriptSummary.repoEntrypoints,
      repoTypeScriptFileCount: typeScriptSummary.repoTypeScriptFileCount,
      repoExportedSymbolCount: typeScriptSummary.repoExportedSymbolCount,
      repoPatchSummary: repoPatchSummary || 'No text diff summary was available.',
      repoWorkspaceFileCount: workspaceFiles.length,
      checksPassed: false,
    };
  } catch (error) {
    return {
      repoInspected: false,
      repoBranch: 'unknown',
      repoDirtyFileCount: 0,
      repoDirtySummary: 'inspection unavailable',
      repoChangedFiles: [],
      repoEntrypoints: [],
      repoTypeScriptFileCount: 0,
      repoExportedSymbolCount: 0,
      repoPatchSummary: '',
      repoWorkspaceFileCount: 0,
      repoInspectionError: error instanceof Error ? error.message : 'Repository snapshot unavailable',
      checksPassed: false,
    };
  }
}

