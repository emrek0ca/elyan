import { createRequire } from "node:module";

/**
 * TEK KAYNAK: `contracts/model-policy.json`.
 *
 * Sunucu ve masaüstü aynı model politikasını paylaşır. Masaüstündeki
 * `runtime/model_roles.py` bu dosyadan üretilir
 * (`npm run models:export`), envanterdeki adlar sağlayıcının canlı kataloğuna
 * karşı doğrulanır (`npm run models:verify`).
 *
 * Canlı gerekçe (2026-08-21): iki taraf model listelerini ayrı ayrı elle
 * tutuyordu ve sürüklendiler; masaüstünün yedek zincirinde sağlayıcının artık
 * sunmadığı modeller kalmıştı ve ilk yedek denemesi sessizce çöpe gidiyordu.
 */
export type ProviderModelSet = {
  inventory: string[];
  retired: string[];
  roles: Record<string, string>;
};

export type ModelPolicy = {
  contract: "elyan.model_policy.v1";
  provider: string;
  /** Groq envanteri — masaüstü rol üreticisi bu şekli okur. */
  inventory: string[];
  retired: string[];
  desktopRoles: Record<string, string[]>;
  gemini: ProviderModelSet;
};

// `resolveJsonModule` ile import etmek dist'e kopyalamayı gerektiriyor;
// contracts/ dizini derleme çıktısına girmediği için JSON çalışma anında
// repo kökünden okunur. Tek kaynak dosyanın kendisidir, kopyası değil.
const require = createRequire(import.meta.url);
const policy = require("../../contracts/model-policy.json") as ModelPolicy;

export const MODEL_POLICY: ModelPolicy = policy;

export const MODEL_INVENTORY: ReadonlySet<string> = new Set(policy.inventory);

/** Sağlayıcı kataloğundan kalkmış modeller. Zincire geri koymak israftır. */
export const RETIRED_MODELS: ReadonlySet<string> = new Set(policy.retired);

export function isRetiredModel(model: string): boolean {
  return RETIRED_MODELS.has(model.trim().toLowerCase());
}

export function isKnownModel(model: string): boolean {
  return MODEL_INVENTORY.has(model.trim());
}

/**
 * GEMINI TARAFI — aynı sözleşme, ikinci sağlayıcı.
 *
 * Canlı arıza (2026-08-22): `GEMINI_FAST_MODEL=gemini-2.5-flash-lite` metadata
 * ucunda 200 dönüyordu ama ÜRETİMDE 404 ("no longer available to new users").
 * Bu yüzden `callGeminiFreeStructured` HER çağrıda null dönüyordu ve uydurma
 * kapısı (`action-claim-gate`) sessizce FAIL-OPEN çalışıyordu: model "şarkıyı
 * çalıyorum" dedi, hiçbir şey çalışmadı, kapı hiç devreye girmedi.
 *
 * Ders: metadata 200 YETMEZ; doğrulama üretim çağrısı olmalıdır
 * (`npm run models:verify`).
 */
export const GEMINI_MODELS: ProviderModelSet = policy.gemini;

export const GEMINI_INVENTORY: ReadonlySet<string> = new Set(policy.gemini.inventory);

export const GEMINI_RETIRED: ReadonlySet<string> = new Set(policy.gemini.retired);

export function geminiRole(role: keyof typeof policy.gemini.roles | string): string {
  return policy.gemini.roles[role] ?? "";
}

export function isRetiredGeminiModel(model: string): boolean {
  return GEMINI_RETIRED.has(model.trim());
}
