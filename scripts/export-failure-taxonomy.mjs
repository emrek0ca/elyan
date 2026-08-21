#!/usr/bin/env node
/**
 * Masaüstü hata taksonomisini TEK KAYNAKTAN üretir.
 *
 * Kaynak: contracts/failure-taxonomy.json
 * Hedef : <elyan-desktop>/runtime/failure_taxonomy.py
 *
 * Gerekçe (canlı, 2026-08-21): tablo sunucuda üretiliyor ve iş emrine
 * yazılıyordu, ama masaüstünde OKUNMUYORDU; masaüstü kendi metin-eşleşmeli
 * merdivenini kullanıyordu. `CAPABILITY_SCOPE_MISMATCH` bu yüzden güvenlik
 * reddi sanıldı ve tur yarım yan etkiyle öldü.
 */
import { readFileSync, writeFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { dirname, resolve } from "node:path";

const here = dirname(fileURLToPath(import.meta.url));
const taxonomy = JSON.parse(
  readFileSync(resolve(here, "..", "contracts", "failure-taxonomy.json"), "utf8"),
);

const target =
  process.argv[2] ?? "/Users/emrekoca/Desktop/elyan/runtime/failure_taxonomy.py";

const codes = new Set(taxonomy.entries.map((entry) => entry.code));
for (const code of taxonomy.authorizationCodes) {
  if (!codes.has(code)) {
    throw new Error(`authorizationCodes bilinmeyen kod içeriyor: ${code}`);
  }
}

const py = (value) => JSON.stringify(value);
const entryLines = taxonomy.entries
  .map(
    (entry) =>
      `    ${py(entry.code)}: FailureRule(\n` +
      `        failure_class=${py(entry.class)},\n` +
      `        retryable=${entry.retryable ? "True" : "False"},\n` +
      `        replan_allowed=${entry.replanAllowed ? "True" : "False"},\n` +
      `    ),`,
  )
  .join("\n");

const body = `"""ÜRETİLEN DOSYA — ELLE DÜZENLEME.

Kaynak: elyan-backend/contracts/failure-taxonomy.json
Yeniden üretim: node scripts/export-failure-taxonomy.mjs <bu dosya>

Sunucu bu tabloyu iş emrine \`failurePolicy.taxonomy\` olarak yazar; masaüstü
aynı tabloyu buradan okur. Canlı arıza (2026-08-21): tablo sunucuda üretiliyor
ama masaüstünde okunmuyordu; masaüstü metin-eşleşmeli kendi merdivenini
kullandığı için \`CAPABILITY_SCOPE_MISMATCH\` güvenlik reddi sanıldı ve tur
yarım yan etkiyle öldü.
"""

from __future__ import annotations

from dataclasses import dataclass

FAILURE_TAXONOMY_CONTRACT = ${py(taxonomy.contract)}


@dataclass(frozen=True)
class FailureRule:
    failure_class: str
    retryable: bool
    replan_allowed: bool


FAILURE_RULES: dict[str, FailureRule] = {
${entryLines}
}

UNKNOWN_FAILURE_RULE = FailureRule(
    failure_class=${py(taxonomy.unknownDefault.class)},
    retryable=${taxonomy.unknownDefault.retryable ? "True" : "False"},
    replan_allowed=${taxonomy.unknownDefault.replanAllowed ? "True" : "False"},
)

# Yetkilendirme kapısından gelen kodlar. Bunların dışındakiler araç/doğrulama
# hatasıdır ve zaten replan yolundan geçer.
AUTHORIZATION_FAILURE_CODES: frozenset[str] = frozenset(
    {
${taxonomy.authorizationCodes.map((code) => `        ${py(code)},`).join("\n")}
    }
)


def failure_rule(code: str) -> FailureRule:
    """Kod için kuralı döndür; bilinmeyen kod güvenli varsayılana düşer."""
    return FAILURE_RULES.get(str(code or "").strip().upper(), UNKNOWN_FAILURE_RULE)
`;

writeFileSync(target, body, "utf8");
console.log(`failure taxonomy written: ${target}`);
