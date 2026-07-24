import { createHash } from 'node:crypto';
import { copyFile, readFile } from 'node:fs/promises';
import { resolve } from 'node:path';

const websiteRoot = resolve(import.meta.dirname, '..');
const backendRoot = String(process.env.ELYAN_BACKEND_ROOT || '').trim();
if (!backendRoot) throw new Error('ELYAN_BACKEND_ROOT is required to sync the generated backend schema.');
const source = resolve(backendRoot, 'contracts/generated/assistant-blocks.schema.json');
const destination = resolve(websiteRoot, 'src/contracts/assistant-blocks.schema.json');
const expectedContractDigest = 'e4d362d3126336edf367b7df4263ca6ba3d777fea63b55d3ad34ab4a869cfb5b';

const contents = await readFile(source);
const schema = JSON.parse(contents.toString('utf8'));
if (schema['x-elyan-schema-digest'] !== expectedContractDigest) {
  throw new Error(`Assistant block contract changed (${schema['x-elyan-schema-digest'] || 'missing digest'}). Review renderer parity before syncing.`);
}
await copyFile(source, destination);
console.log(`Synced assistant block schema (${createHash('sha256').update(contents).digest('hex')}).`);
