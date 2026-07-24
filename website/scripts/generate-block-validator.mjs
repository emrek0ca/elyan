import Ajv2020 from 'ajv/dist/2020.js';
import standaloneCode from 'ajv/dist/standalone/index.js';
import { readFile, writeFile } from 'node:fs/promises';
import { resolve } from 'node:path';

const root = resolve(import.meta.dirname, '..');
const schemaPath = resolve(root, 'src/contracts/assistant-blocks.schema.json');
const outputPath = resolve(root, 'src/contracts/assistant-blocks.validator.mjs');
const schema = JSON.parse(await readFile(schemaPath, 'utf8'));
const ajv = new Ajv2020({ allErrors: true, strict: false, validateFormats: false, code: { source: true, esm: true, optimize: true } });
const validate = ajv.compile(schema);
const ucs2LengthHelper = `function ucs2length(str){let length=0;for(let index=0;index<str.length;index+=1){length+=1;const code=str.charCodeAt(index);if(code>=55296&&code<=56319&&index+1<str.length){const next=str.charCodeAt(index+1);if(next>=56320&&next<=57343)index+=1;}}return length;}`;
let source = `${standaloneCode(ajv, validate)}\n`;
source = source.replace(
  /const (func\d+) = require\("ajv\/dist\/runtime\/ucs2length"\)\.default;/,
  `const $1 = ${ucs2LengthHelper};`,
);
if (/\brequire\(|\bmodule\.exports\b|\bexports\./.test(source)) {
  throw new Error('Generated assistant block validator is not browser-safe ESM.');
}
await writeFile(outputPath, source, 'utf8');
console.log(`Generated CSP-safe AJV validator (${Buffer.byteLength(source)} bytes).`);
