#!/usr/bin/env node
/**
 * TypeScript script'ini DERLENMİŞ haliyle çalıştırır, yoksa tsx'e düşer.
 *
 * NEDEN VAR: üretim imajı `devDependencies`i buduyor, yani `tsx` orada YOK.
 * `npm run retrieval:backfill-hash` gibi tsx ile tanımlı 29 script sunucuda
 * `MODULE_NOT_FOUND` ile kırılıyor — bugün canlıda tam olarak bu oldu ve
 * göç elle `node dist/scripts/...js` çağrılarak yürütüldü.
 *
 * Sıra bilinçli: `dist` varsa o kullanılır (üretim yolu, ek bağımlılık yok),
 * yoksa `tsx` (geliştirme yolu, derleme beklemeden koşar).
 *
 *   node scripts/run-ts.mjs src/scripts/backfill-hashed-embeddings.ts [args]
 */
import { existsSync } from "node:fs";
import { spawn } from "node:child_process";
import { resolve } from "node:path";

const [entry, ...rest] = process.argv.slice(2);
if (!entry) {
  console.error("kullanım: node scripts/run-ts.mjs <src/...ts> [args]");
  process.exit(1);
}

const compiled = resolve(entry.replace(/^src\//, "dist/").replace(/\.ts$/, ".js"));
const useCompiled = existsSync(compiled);
const command = useCompiled
  ? [process.execPath, compiled, ...rest]
  : [process.execPath, resolve("node_modules/tsx/dist/cli.mjs"), entry, ...rest];

if (!useCompiled && !existsSync(command[1])) {
  console.error(
    `Ne derlenmiş dosya (${compiled}) ne de tsx bulundu. Önce: npm run build`,
  );
  process.exit(1);
}

spawn(command[0], command.slice(1), { stdio: "inherit" }).on("exit", (code) =>
  process.exit(code ?? 1),
);
