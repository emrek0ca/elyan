import { airQualityProvider } from "./providers/air-quality.js";
import { cryptoProvider } from "./providers/crypto.js";
import { earthquakeProvider } from "./providers/earthquake.js";
import { fxProvider } from "./providers/fx.js";
import { holidayProvider } from "./providers/holidays.js";
import { localTimeProvider } from "./providers/local-time.js";
import { weatherProvider } from "./providers/weather.js";
import type { FactProvider, FactProviderId } from "./types.js";

/**
 * Sağlayıcı kataloğu. Yeni bir kaynak eklemek = bu listeye bir satır.
 *
 * Kapsam BİLEREK dar tutulur: tipli, sayısal, doğrulanabilir ve sık sorulan
 * alanlar. Haber/yorum/karşılaştırma gibi cevabı düzyazı olan sorular buraya
 * GİRMEZ — onların tipli bir API'si yoktur ve arama şeridinde kalmaları
 * doğrudur.
 */
export const FACT_PROVIDERS: FactProvider<unknown>[] = [
  weatherProvider,
  airQualityProvider,
  fxProvider,
  cryptoProvider,
  localTimeProvider,
  earthquakeProvider,
  holidayProvider,
];

export function getFactProvider(id: FactProviderId): FactProvider<unknown> | null {
  return FACT_PROVIDERS.find((provider) => provider.id === id) ?? null;
}
