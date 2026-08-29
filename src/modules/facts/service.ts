import type { FastifyInstance } from "fastify";
import { createHash } from "node:crypto";
import { recordStageDuration } from "../../lib/perf-telemetry.js";
import { readFactCache, revalidateFactInBackground, writeFactCache } from "./cache.js";
import { isFactProviderCircuitOpen } from "./http.js";
import { FACT_PROVIDERS } from "./registry.js";
import { selectFactProviders, type FactSelection } from "./select.js";
import type { FactAnswer, FactProvider } from "./types.js";

const inflight = new Map<string, Promise<FactAnswer | null>>();

function factSecrets(app: FastifyInstance) {
  return {
    alphaVantageApiKey: app.config.ALPHA_VANTAGE_API_KEY || undefined,
    tcmbEvdsApiKey: app.config.TCMB_EVDS_API_KEY || undefined,
    fredApiKey: app.config.FRED_API_KEY || undefined,
    coinGeckoDemoApiKey: app.config.COINGECKO_DEMO_API_KEY || undefined,
    crossrefMailto: app.config.CROSSREF_MAILTO || undefined,
  };
}

function withSourceDescriptor(
  provider: FactProvider<unknown>,
  answer: FactAnswer,
): FactAnswer {
  if (answer.source) return answer;
  const retrievedAt = new Date().toISOString();
  const sourceHash = createHash("sha256")
    .update(
      JSON.stringify({
        providerId: answer.providerId,
        sourceHost: answer.citation.sourceHost,
        observedAt: answer.citation.observedAt,
        values: answer.values,
      }),
    )
    .digest("hex");
  return {
    ...answer,
    source: {
      authority: provider.authority,
      dataClass: answer.dataClass,
      observedAt: answer.citation.observedAt,
      retrievedAt,
      expiresAt: new Date(Date.now() + answer.ttlMs).toISOString(),
      units: provider.units ?? [],
      requiresSecret: provider.requiresSecret != null,
      commercialUse: provider.commercialUse,
      sourceHash,
      verificationState: answer.confidence >= 0.85 ? "verified" : "partial",
    },
  };
}

/**
 * Olgu katmanının tek giriş noktası.
 *
 * Sözleşme: ya TİPLİ ve KAYNAKLI bir cevap döner, ya da `null`. `null`
 * çağıranın normal web temellendirmesine düşmesi demektir. Bu katman hiçbir
 * koşulda "yaklaşık" bir sayı ya da modelden gelen bir tahmin üretmez.
 */

export type FactResolution = {
  answer: FactAnswer;
  selection: "semantic" | "domain_fallback";
  cacheState: "miss" | "fresh" | "stale";
};

function isEnabled(app: FastifyInstance): boolean {
  return app.config?.ELYAN_FACT_PROVIDERS_ENABLED !== false;
}

/**
 * e5 yokken kullanılan YEDEK: mevcut `FreshDataPolicy.domain` sinyali.
 * Yeni bir sözcük-deseni sahibi yaratmamak için üst akıştaki karar aynen
 * kullanılır; karşılığı olmayan sağlayıcı bu yoldan asla seçilmez.
 */
function providersForDomain(domain: string | undefined): FactProvider<unknown>[] {
  if (domain !== "weather" && domain !== "market") return [];
  return FACT_PROVIDERS.filter((provider) => provider.fallbackDomain === domain);
}

async function resolveWithProvider(
  app: FastifyInstance,
  provider: FactProvider<unknown>,
  prompt: string,
  bypassCache: boolean,
): Promise<{ answer: FactAnswer; cacheState: "miss" | "fresh" | "stale" } | null> {
  if (isFactProviderCircuitOpen(provider.id)) return null;
  const secrets = factSecrets(app);
  if (provider.requiresSecret && !secrets[provider.requiresSecret]) return null;
  const params = provider.extract(prompt);
  if (params === null || params === undefined) return null;
  const key = `${provider.id}:${provider.cacheKey(params)}`;

  // `bypassCache` çağıranın "bana taze veri getir" sözleşmesidir ve HER İKİ
  // yönde geçerlidir: bu turda ne önbellekten okunur ne de önbelleğe yazılır.
  // Yalnız okumayı atlamak, taze isteyen bir turun sonucunu bir sonraki
  // sıradan tura sızdırır — ölçüldü: regresyon paketinde bir testin cevabı
  // diğerinin turunda önbellekten dönüyordu.
  const cached = bypassCache ? null : await readFactCache(app, key);
  if (cached?.state === "fresh") {
    return {
      answer: withSourceDescriptor(provider, cached.answer),
      cacheState: "fresh",
    };
  }

  const fetchFresh = async (): Promise<FactAnswer | null> => {
    const inflightKey = `${key}:${bypassCache ? "bypass" : "cached"}`;
    let request = inflight.get(inflightKey);
    if (!request) {
      request = provider
        .resolve(
          { timeoutMs: provider.timeoutMs, logger: app.log, secrets },
          params,
        )
        .then((answer) =>
          answer ? withSourceDescriptor(provider, answer) : null,
        )
        .finally(() => inflight.delete(inflightKey));
      inflight.set(inflightKey, request);
    }
    const answer = await request;
    if (answer && !bypassCache) await writeFactCache(app, key, answer);
    return answer;
  };

  if (cached?.state === "stale" && provider.allowStale) {
    // Bayat cevabı ANINDA ver, tazelemeyi arkada çalıştır.
    revalidateFactInBackground(key, async () => {
      await fetchFresh().catch(() => null);
    });
    return {
      answer: withSourceDescriptor(provider, cached.answer),
      cacheState: "stale",
    };
  }

  try {
    const answer = await fetchFresh();
    return answer ? { answer, cacheState: "miss" } : null;
  } catch (error) {
    app.log?.debug?.(
      {
        providerId: provider.id,
        reason: error instanceof Error ? error.message : "fact_provider_failed",
      },
      "fact provider unavailable, falling back to web grounding",
    );
    return null;
  }
}

export async function resolveFactAnswer(
  app: FastifyInstance,
  input: {
    prompt: string;
    domain?: string;
    bypassCache?: boolean;
    shortlist?: FactSelection[];
    queryVector?: number[] | null;
  },
): Promise<FactResolution | null> {
  if (!isEnabled(app)) return null;
  const prompt = String(input.prompt ?? "").trim();
  if (!prompt) return null;

  const endStage = recordFactStage();
  try {
    // Anlamsal kısa liste: yakın-beraberlikteki adaylar sırayla denenir.
    // Sağlayıcı turda kendi varlığını bulamazsa `extract` zaten null döner,
    // yani bu döngü asla kullanıcının sormadığı veriyi getirmez.
    // Kısa liste seçimi ile SAĞLAYICI DENEMELERİ ayrı ölçülür: 841 ms'lik
    // olgu maliyetinin hangisinden geldiği ölçülmeden bilinemezdi.
    const endSelectStage = recordFactStageNamed("facts.select");
    const shortlist =
      input.shortlist ??
      (await selectFactProviders({
        prompt,
        queryVector: input.queryVector,
        logger: app.log,
      }));
    endSelectStage();
    const attempted = new Set<string>();
    for (const candidate of shortlist) {
      attempted.add(candidate.provider.id);
      const resolved = await resolveWithProvider(
        app,
        candidate.provider,
        prompt,
        input.bypassCache === true,
      );
      if (resolved) {
        return { ...resolved, selection: "semantic" };
      }
    }

    // e5 yoksa ya da kısa listedeki adaylar cevap üretemediyse, üst akıştaki
    // domain sinyali devralır. Bu, e5 kesintisinde eski davranışın korunduğu
    // tek yoldur; yeni bir sözcük-deseni sahibi yaratmaz.
    for (const provider of providersForDomain(input.domain)) {
      if (attempted.has(provider.id)) continue;
      const resolved = await resolveWithProvider(
        app,
        provider,
        prompt,
        input.bypassCache === true,
      );
      if (resolved) {
        return { ...resolved, selection: "domain_fallback" };
      }
    }
    return null;
  } finally {
    endStage();
  }
}

function recordFactStageNamed(stage: string): () => void {
  const startedAt = Date.now();
  return () => recordStageDuration(stage, Date.now() - startedAt);
}

function recordFactStage(): () => void {
  const startedAt = Date.now();
  return () => recordStageDuration("facts.resolve", Date.now() - startedAt);
}

export { FACT_PROVIDERS } from "./registry.js";
export type { FactAnswer } from "./types.js";
