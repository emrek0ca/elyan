#!/usr/bin/env node
/**
 * `contracts/model-policy.json` envanterini SAĞLAYICILARIN CANLI DAVRANIŞINA
 * karşı doğrular — Groq ve Gemini.
 *
 * KRİTİK: doğrulama ÜRETİM çağrısıdır, katalog/metadata listesi DEĞİL.
 * Canlı arıza (2026-08-22): `gemini-2.5-flash-lite` metadata ucunda 200
 * dönüyordu ama üretimde 404 ("no longer available to new users"). Model
 * "yaşıyor" göründüğü için kimse fark etmedi; sonuçta `callGeminiFreeStructured`
 * HER çağrıda null döndü ve uydurma kapısı (action-claim-gate) sessizce
 * fail-open çalıştı — asistan "şarkıyı çalıyorum" dedi, hiçbir şey çalışmadı.
 *
 * Kullanım: node --env-file-if-exists=.env scripts/verify-model-inventory.mjs
 * Çıkış kodu 0 = envanterin tamamı gerçekten üretim yapıyor.
 */
import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { dirname, resolve } from "node:path";

const here = dirname(fileURLToPath(import.meta.url));
const policy = JSON.parse(
  readFileSync(resolve(here, "..", "contracts", "model-policy.json"), "utf8"),
);

const PROBE = {
  max_tokens: 220,
  messages: [{ role: "user", content: 'Reply with JSON {"ok":true} only.' }],
};

async function probe(baseUrl, apiKey, model) {
  try {
    const response = await fetch(`${baseUrl}/chat/completions`, {
      method: "POST",
      headers: {
        Authorization: `Bearer ${apiKey}`,
        "Content-Type": "application/json",
      },
      body: JSON.stringify({ model, ...PROBE }),
    });
    if (!response.ok) {
      const detail = (await response.text()).replace(/\s+/g, " ").slice(0, 120);
      return { ok: false, detail: `HTTP ${response.status} ${detail}` };
    }
    const body = await response.json();
    const content = body.choices?.[0]?.message?.content ?? "";
    return content.trim()
      ? { ok: true }
      : { ok: false, detail: "boş üretim (finish=" + (body.choices?.[0]?.finish_reason ?? "?") + ")" };
  } catch (error) {
    return { ok: false, detail: String(error).slice(0, 120) };
  }
}

async function verifyProvider({ label, baseUrl, apiKey, inventory, retired }) {
  if (!apiKey) {
    console.warn(`${label}: anahtar yok — atlandı.`);
    return { skipped: true, dead: [] };
  }
  const dead = [];
  for (const model of inventory) {
    const result = await probe(baseUrl, apiKey, model);
    if (result.ok) {
      console.log(`  ok    ${label}/${model}`);
    } else {
      dead.push(model);
      console.error(`  DEAD  ${label}/${model} — ${result.detail}`);
    }
  }
  for (const model of retired) {
    const result = await probe(baseUrl, apiKey, model);
    if (result.ok) {
      console.warn(`  bilgi: emekli sayılan ${label}/${model} yeniden üretim yapıyor`);
    }
  }
  return { skipped: false, dead };
}

const results = [];
results.push(
  await verifyProvider({
    label: "groq",
    baseUrl: process.env.GROQ_BASE_URL ?? "https://api.groq.com/openai/v1",
    apiKey: process.env.GROQ_API_KEY,
    inventory: policy.inventory,
    retired: policy.retired,
  }),
);
results.push(
  await verifyProvider({
    label: "gemini",
    baseUrl:
      process.env.GEMINI_BASE_URL ??
      "https://generativelanguage.googleapis.com/v1beta/openai",
    apiKey: process.env.GEMINI_API_KEY,
    inventory: policy.gemini.inventory,
    retired: policy.gemini.retired,
  }),
);

const dead = results.flatMap((result) => result.dead);
if (dead.length > 0) {
  console.error(
    `\n${dead.length} model ÜRETİM YAPMIYOR. contracts/model-policy.json güncelle, ` +
      "sonra: npm run models:export",
  );
  process.exit(1);
}
if (results.every((result) => result.skipped)) {
  console.error("hiçbir sağlayıcı anahtarı yok — doğrulama yapılamadı.");
  process.exit(2);
}

// ENVANTER DOĞRUYKEN YAPILANDIRMA YANLIŞ OLABİLİR.
//
// Bu araç bugüne kadar yalnız `contracts/model-policy.json` envanterini
// doğruluyordu ve o hep yeşildi — ama üretimde kullanılan ad ortam
// değişkeninden geliyor. `GEMINI_FAST_MODEL=gemini-2.5-flash-lite` aylarca
// öyle kaldı: politikanın kendi `retired` listesinde bir ad, sağlayıcıda 404.
// Sonuç, ona bağlı her yardımcı çağrının sessizce null dönmesi ve uydurma
// kapısının tamamen kapanmasıydı (2026-08-28).
//
// Envanteri doğrulayıp yapılandırmayı doğrulamamak, doğru listeyi kontrol
// edip yanlış listeyi kullanmaktır.
const retiredGemini = new Set(policy.gemini.retired);
const retiredGroq = new Set(policy.groq?.retired ?? []);
const CONFIGURED_MODEL_VARS = [
  ["GEMINI_FAST_MODEL", retiredGemini],
  ["GEMINI_TEXT_MODEL", retiredGemini],
  ["GEMINI_REASONING_MODEL", retiredGemini],
  ["GEMINI_VISION_MODEL", retiredGemini],
  ["GEMINI_IMAGE_MODEL", retiredGemini],
  ["GROQ_FAST_MODEL", retiredGroq],
  ["GROQ_REASONING_MODEL", retiredGroq],
  ["GROQ_FALLBACK_MODEL", retiredGroq],
];

const configuredRetired = [];
for (const [variable, retired] of CONFIGURED_MODEL_VARS) {
  const value = String(process.env[variable] ?? "").trim();
  if (value && retired.has(value)) {
    configuredRetired.push(`${variable}=${value}`);
  }
}

if (configuredRetired.length > 0) {
  console.error("\nEMEKLİ MODEL YAPILANDIRILMIŞ:");
  for (const entry of configuredRetired) console.error(`  ${entry}`);
  console.error(
    "Bu adlar politikada emekli; sağlayıcı 404 döner ve onlara bağlı çağrılar " +
      "sessizce devre dışı kalır. Ortam değişkenini kaldır ya da canlı bir ada çevir.",
  );
  process.exit(1);
}

console.log("\nenvanterin tamamı canlı üretim yapıyor.");
console.log("yapılandırılmış model adlarında emekli ad yok.");
