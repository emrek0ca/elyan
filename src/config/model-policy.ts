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
export type ModelPolicy = {
  contract: "elyan.model_policy.v1";
  provider: string;
  inventory: string[];
  retired: string[];
  desktopRoles: Record<string, string[]>;
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
