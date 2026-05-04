#!/usr/bin/env node

import path from 'path';
import { mkdir, writeFile } from 'fs/promises';
import { runBootstrapPipeline } from '../src/core/ml';

function parseArg(name: string, fallback?: string) {
  const index = process.argv.findIndex((arg) => arg === name);
  if (index === -1) {
    return fallback;
  }

  const next = process.argv[index + 1];
  return next && !next.startsWith('-') ? next : fallback;
}

async function ensureTemplateManifest(manifestPath: string) {
  const template = {
    sources: [],
    chunkSize: 1400,
    overlap: 160,
    maxChunksPerSource: 20,
  };

  await mkdir(path.dirname(manifestPath), { recursive: true });
  await writeFile(manifestPath, `${JSON.stringify(template, null, 2)}\n`, 'utf8');
  return template;
}

async function main() {
  const manifestPath =
    parseArg('--manifest', process.env.ELYAN_ML_BOOTSTRAP_MANIFEST) ||
    path.resolve(process.cwd(), 'storage', 'ml', 'bootstrap', 'bootstrap-manifest.json');
  const outputDir =
    parseArg('--output-dir', process.env.ELYAN_ML_BOOTSTRAP_OUTPUT_DIR) ||
    path.resolve(process.cwd(), 'storage', 'ml', 'bootstrap');

  try {
    const result = await runBootstrapPipeline(manifestPath, outputDir);
    console.log(JSON.stringify(result, null, 2));
    return;
  } catch (error) {
    const message = error instanceof Error ? error.message : String(error);
    if (message.includes('ENOENT')) {
      const template = await ensureTemplateManifest(manifestPath);
      console.log(
        JSON.stringify(
          {
            ok: true,
            template_created: true,
            manifest_path: manifestPath,
            output_dir: outputDir,
            template,
          },
          null,
          2
        )
      );
      return;
    }

    throw error;
  }
}

main().catch((error) => {
  console.error(error instanceof Error ? error.stack || error.message : String(error));
  process.exit(1);
});
