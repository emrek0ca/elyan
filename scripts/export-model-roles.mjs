#!/usr/bin/env node
/**
 * Masaüstü model rollerini TEK KAYNAKTAN üretir.
 *
 * Kaynak: contracts/model-policy.json
 * Hedef : <elyan-desktop>/runtime/model_roles.py
 *
 * Gerekçe (canlı, 2026-08-21): sunucu ve masaüstü model listelerini AYRI AYRI
 * elle tutuyordu ve sürüklendiler — masaüstünün yedek zincirinde Groq'un artık
 * sunmadığı iki model (`llama-3.3-70b-versatile`, `llama-3.1-8b-instant`) kaldı.
 * Birincil model geçersiz JSON döndürdüğünde masaüstü OLMAYAN bir modele
 * düşüyordu: sunucuda o gün temizlenen israfın birebir aynısı, diğer uçta.
 *
 * Kullanım:
 *   node scripts/export-model-roles.mjs /Users/emrekoca/Desktop/elyan/runtime/model_roles.py
 */
import { readFileSync, writeFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { dirname, resolve } from "node:path";

const here = dirname(fileURLToPath(import.meta.url));
const policyPath = resolve(here, "..", "contracts", "model-policy.json");
const policy = JSON.parse(readFileSync(policyPath, "utf8"));

const target =
  process.argv[2] ?? "/Users/emrekoca/Desktop/elyan/runtime/model_roles.py";

const inventory = new Set(policy.inventory);
const retired = new Set(policy.retired);
for (const [role, models] of Object.entries(policy.desktopRoles)) {
  for (const model of models) {
    if (retired.has(model)) {
      throw new Error(`role "${role}" emekli modeli kullanıyor: ${model}`);
    }
    if (!inventory.has(model)) {
      throw new Error(`role "${role}" envanterde olmayan model kullanıyor: ${model}`);
    }
  }
}

const roleLines = Object.entries(policy.desktopRoles)
  .map(([role, models]) => {
    const items = models.map((model) => `        ${JSON.stringify(model)},`).join("\n");
    return `    ${JSON.stringify(role)}: (\n${items}\n    ),`;
  })
  .join("\n");

const body = `"""ÜRETİLEN DOSYA — ELLE DÜZENLEME.

Kaynak: elyan-backend/contracts/model-policy.json
Yeniden üretim: node scripts/export-model-roles.mjs <bu dosya>

Sunucu ve masaüstü aynı model politikasını paylaşır. İki tarafta elle tutulan
liste sürüklenmesi canlı arıza sınıfıdır: masaüstünün yedek zincirinde
sağlayıcının artık sunmadığı modeller kalmıştı ve birincil model geçersiz JSON
döndürdüğünde OLMAYAN bir modele düşülüyordu.
"""

from __future__ import annotations

MODEL_POLICY_CONTRACT = ${JSON.stringify(policy.contract)}

# Sağlayıcının canlı kataloğunda bulunduğu doğrulanmış modeller.
MODEL_INVENTORY: tuple[str, ...] = (
${policy.inventory.map((m) => `    ${JSON.stringify(m)},`).join("\n")}
)

# Sağlayıcı kataloğundan KALKMIŞ modeller. Zincire geri koymak, ilk yedek
# denemesini sessizce çöpe atar.
RETIRED_MODELS: frozenset[str] = frozenset(
    {
${policy.retired.map((m) => `        ${JSON.stringify(m)},`).join("\n")}
    }
)

MODEL_ROLES: dict[str, tuple[str, ...]] = {
${roleLines}
}
`;

writeFileSync(target, body, "utf8");
console.log(`model roles written: ${target}`);
