import { ZipArchive } from 'archiver';
import { mkdir, rm } from 'node:fs/promises';
import { createWriteStream } from 'node:fs';
import { resolve } from 'node:path';

const root = resolve(import.meta.dirname, '..');
const releaseDir = resolve(root, 'release');
const outputPath = resolve(releaseDir, 'elyan-website-hostinger.zip');
await mkdir(releaseDir, { recursive: true });
await rm(outputPath, { force: true });

const output = createWriteStream(outputPath);
const archive = new ZipArchive({ zlib: { level: 9 } });
const completed = new Promise((resolvePromise, reject) => {
  output.on('close', resolvePromise);
  output.on('error', reject);
  archive.on('error', reject);
});
archive.pipe(output);

for (const file of ['package.json', 'package-lock.json', 'astro.config.mjs', 'tsconfig.json', '.env.example', 'HOSTINGER_DEPLOY.md']) {
  archive.file(resolve(root, file), { name: file });
}
archive.directory(resolve(root, 'src'), 'src');
archive.directory(resolve(root, 'public'), 'public');
archive.directory(resolve(root, 'scripts'), 'scripts');
await archive.finalize();
await completed;
console.log(`Created ${outputPath} (${archive.pointer()} bytes).`);
