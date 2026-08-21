import { createRequire } from "node:module";

/**
 * TEK KAYNAK: `contracts/failure-taxonomy.json`.
 *
 * Sunucu bu tabloyu iş emrine `failurePolicy.taxonomy` olarak yazar; masaüstü
 * aynı kaynaktan üretilen `runtime/failure_taxonomy.py` ile okur.
 *
 * Canlı gerekçe (2026-08-21): tablo sunucuda üretiliyordu ama masaüstünde
 * OKUNMUYORDU; masaüstü kendi metin-eşleşmeli merdivenini kullanıyordu
 * ("PERMISSION" geçiyorsa izin hatası…). Sonuç: `CAPABILITY_SCOPE_MISMATCH`
 * güvenlik reddi sanılıp tur yarım yan etkiyle öldü (Safari açıldı, YouTube
 * açılmadı). Aynı kararın iki sahibi olmamalı.
 */
export const FAILURE_CLASSES = [
  "dependency",
  "permission",
  "capability",
  "verification",
  "model",
  "timeout",
  "cancelled",
] as const;

export type FailureClass = (typeof FAILURE_CLASSES)[number];

export type FailureTaxonomyEntry = {
  code: string;
  class: FailureClass;
  retryable: boolean;
  replanAllowed: boolean;
};

export type FailureTaxonomy = {
  contract: "elyan.failure_taxonomy.v1";
  entries: FailureTaxonomyEntry[];
  unknownDefault: Omit<FailureTaxonomyEntry, "code">;
  authorizationCodes: string[];
};

const require = createRequire(import.meta.url);
const taxonomy = require("../../contracts/failure-taxonomy.json") as FailureTaxonomy;

// Kaynak dosya elle düzenlenebilir; bilinmeyen bir sınıf sessizce geçmemeli.
for (const entry of taxonomy.entries) {
  if (!FAILURE_CLASSES.includes(entry.class)) {
    throw new Error(
      `failure-taxonomy.json: bilinmeyen sınıf "${entry.class}" (${entry.code})`,
    );
  }
}

export const FAILURE_TAXONOMY: FailureTaxonomy = taxonomy;

const byCode = new Map(taxonomy.entries.map((entry) => [entry.code, entry]));

export function failureTaxonomyEntries(): FailureTaxonomyEntry[] {
  return taxonomy.entries.map((entry) => ({ ...entry }));
}

export function classifyFailureCode(code: string): FailureTaxonomyEntry {
  const normalized = String(code ?? "").trim().toUpperCase();
  const entry = byCode.get(normalized);
  return entry
    ? { ...entry }
    : { code: normalized, ...taxonomy.unknownDefault };
}

/** Yetkilendirme hatası mı (yoksa araç/doğrulama hatası mı)? */
export function isAuthorizationFailureCode(code: string): boolean {
  return taxonomy.authorizationCodes.includes(
    String(code ?? "").trim().toUpperCase(),
  );
}
