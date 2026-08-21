#!/usr/bin/env node
/**
 * `contracts/model-policy.json` envanterini SAĞLAYICININ CANLI KATALOĞUNA karşı
 * doğrular. Model adları sessizce kalkar; kalkan bir ad zincirde kaldığında ilk
 * yedek denemesi çöpe gider (canlı, 2026-08-21).
 *
 * Kullanım: GROQ_API_KEY=... node scripts/verify-model-inventory.mjs
 * Çıkış kodu 0 = envanter canlı katalogla uyumlu.
 */
import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { dirname, resolve } from "node:path";

const here = dirname(fileURLToPath(import.meta.url));
const policy = JSON.parse(
  readFileSync(resolve(here, "..", "contracts", "model-policy.json"), "utf8"),
);

const apiKey = process.env.GROQ_API_KEY;
if (!apiKey) {
  console.error("GROQ_API_KEY yok — doğrulama çalıştırılamadı.");
  process.exit(2);
}

const baseUrl = process.env.GROQ_BASE_URL ?? "https://api.groq.com/openai/v1";
const response = await fetch(`${baseUrl}/models`, {
  headers: { Authorization: `Bearer ${apiKey}` },
});
if (!response.ok) {
  console.error(`katalog okunamadı: HTTP ${response.status}`);
  process.exit(2);
}
const body = await response.json();
const live = new Set((body.data ?? []).map((entry) => entry.id));

const missing = policy.inventory.filter((model) => !live.has(model));
const resurrected = policy.retired.filter((model) => live.has(model));

for (const model of missing) {
  console.error(`ENVANTER BAYAT: ${model} canlı katalogda yok`);
}
for (const model of resurrected) {
  console.warn(`bilgi: emekli sayılan ${model} katalogda yeniden görünüyor`);
}

if (missing.length > 0) {
  console.error(
    `\n${missing.length} model kalkmış. contracts/model-policy.json güncelle, ` +
      "sonra: npm run models:export",
  );
  process.exit(1);
}
console.log(
  `envanter canlı katalogla uyumlu (${policy.inventory.length} model, ${live.size} katalog girdisi).`,
);
