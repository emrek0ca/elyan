import { fetchFactJson, finiteNumber, readRecord } from "../http.js";
import { matchCryptoAsset } from "../catalog.js";
import { defineFactProvider, type FactAnswer } from "../types.js";

/**
 * Kripto fiyatı (CoinGecko public API).
 *
 * Varlık seçimi KATALOGDAN gelir; eski regex yalnız BTC ve ETH tanıyordu.
 * Sağlayıcı zamanı (`last_updated_at`) doğrulanır — gelecekteki ya da 2017
 * öncesi bir damga verinin bozuk olduğunu gösterir ve cevap üretilmez.
 */

type CryptoParams = { id: string; symbol: string };

export const cryptoProvider = defineFactProvider<CryptoParams>({
  id: "coingecko",
  dataClass: "realtime",
  authority: "CoinGecko",
  commercialUse: "conditional",
  allowStale: false,
  units: ["TRY", "USD"],
  timeoutMs: 4_000,
  ttlMs: 60_000,
  fallbackDomain: "market",
  intents: [
    "bitcoin kaç dolar",
    "ethereum fiyatı ne kadar",
    "solana bugün kaç TL",
    "kripto para fiyatı nedir",
    "btc price right now",
  ],
  extract(prompt) {
    const asset = matchCryptoAsset(prompt);
    return asset ? { id: asset.id, symbol: asset.symbol } : null;
  },
  cacheKey(params) {
    return `crypto:${params.id}`;
  },
  async resolve(context, params): Promise<FactAnswer | null> {
    const url = new URL("https://api.coingecko.com/api/v3/simple/price");
    url.searchParams.set("ids", params.id);
    url.searchParams.set("vs_currencies", "try,usd");
    url.searchParams.set("include_last_updated_at", "true");

    const payload = readRecord(
      await fetchFactJson({
        providerId: "coingecko",
        url: url.toString(),
        timeoutMs: context.timeoutMs,
        maxBytes: 100_000,
        headers: context.secrets.coinGeckoDemoApiKey
          ? { "x-cg-demo-api-key": context.secrets.coinGeckoDemoApiKey }
          : undefined,
      }),
    );
    const quote = readRecord(payload?.[params.id]);
    const tryValue = finiteNumber(quote?.try);
    const usdValue = finiteNumber(quote?.usd);
    const updatedSeconds = finiteNumber(quote?.last_updated_at);
    const nowSeconds = Math.floor(Date.now() / 1_000);
    if (
      tryValue === null ||
      tryValue <= 0 ||
      updatedSeconds === null ||
      updatedSeconds < 1_500_000_000 ||
      updatedSeconds > nowSeconds + 300
    ) {
      return null;
    }
    const observedAt = new Date(updatedSeconds * 1_000).toISOString();
    const snippet = [
      `${params.symbol}/TRY ${tryValue}`,
      usdValue === null ? null : `${params.symbol}/USD ${usdValue}`,
      `sağlayıcı zamanı ${observedAt}`,
    ]
      .filter((value): value is string => Boolean(value))
      .join("; ");

    return {
      providerId: "coingecko",
      dataClass: "realtime",
      snippet,
      directAnswer:
        `${params.symbol} şu an ${tryValue} TRY` +
        (usdValue === null ? "." : ` (${usdValue} USD).`),
      citation: {
        title: `${params.symbol} anlık piyasa verisi`,
        url: url.toString(),
        sourceHost: "api.coingecko.com",
        observedAt,
      },
      values: {
        symbol: params.symbol,
        priceTry: tryValue,
        ...(usdValue === null ? {} : { priceUsd: usdValue }),
      },
      confidence: 0.93,
      ttlMs: 60_000,
    };
  },
});
