import { createHash } from "node:crypto";
import { monitorEventLoopDelay } from "node:perf_hooks";
import { getHeapStatistics } from "node:v8";
import type { FastifyInstance, FastifyReply, FastifyRequest } from "fastify";
import type { AppEnv } from "../../config/env.js";

/**
 * Süreç-içi yük basıncı + hız sınırı anahtarlama.
 *
 * `load-shedding.ts` ile KARIŞTIRMA: orası Redis kilidiyle *eşzamanlı iş
 * sayısını* sınırlar (kaç çıkarım aynı anda koşabilir). Burası ise SÜRECİN
 * KENDİ sağlığına bakar (olay döngüsü doydu mu, heap doldu mu) ve dış
 * saldırı yüzeyini daraltır.
 *
 * ÜÇ SOMUT AÇIK:
 *
 * 1. HIZ SINIRI ATLATMA — sınır IP'ye bakıyor, `trustProxy: true` ise
 *    `X-Forwarded-For` başlığını İNTERNETTEN olduğu gibi kabul ediyordu.
 *    Saldırgan her istekte başlığı değiştirip sınırsız istek atabilirdi.
 *    Anahtar artık ÖNCE bearer token'ın hash'i, yoksa IP.
 *
 * 2. PAHALI ROTALARDA TEK TİP TAVAN — `/healthz` ile LLM çıkarımı aynı
 *    600/dk bütçesini paylaşıyordu. Tek kullanıcı dakikada 600 çıkarım
 *    tetikleyip hem sağlayıcı faturasını hem sunucuyu tüketebilirdi.
 *
 * 3. YÜK ALTINDA ÇÖKME — olay döngüsü doyunca süreç yavaşça kilitleniyordu.
 *    Artık doygunlukta yeni istekler hızlıca 503 + `Retry-After` alır;
 *    süreç ayakta kalır ve kendini toparlar.
 */

/** LLM/medya çağıran, istek başına maliyeti yüksek rota önekleri. */
const EXPENSIVE_ROUTE_PREFIXES = [
  "/v1/chat",
  "/v1/brain",
  "/v1/speech",
  "/v1/tasks",
  "/v1/web",
  "/v1/mcp",
] as const;

/** Kimlik/oturum rotaları — kaba kuvvet ve hesap sayımı burada denenir. */
const AUTH_ROUTE_PREFIXES = ["/v1/auth", "/auth/callback"] as const;

/**
 * Cihaz eşleştirme rotaları.
 *
 * Eskiden auth kovasındaydı (30/dk) ve bu KULLANILAMAZ bir eşleştirme
 * yaratıyordu: eşleştirme ekranı açıkken istemci oturum durumunu YOKLAR, bu
 * yoklama dakikalık auth bütçesini saniyeler içinde bitirir ve kullanıcı
 * kodu doğru girse bile "Rate limit exceeded" görür.
 *
 * Eşleştirme kaba kuvvet yüzeyi DEĞİLDİR (kod kısa ömürlü, tek kullanımlık ve
 * sunucu tarafında üretilir), bu yüzden kendi daha geniş kovasında olmalı —
 * login/parola rotalarının sıkı sınırı olduğu gibi korunur.
 */
const PAIRING_ROUTE_PREFIXES = ["/v1/pairing", "/v1/devices/pairing"] as const;

/** Sağlık yoklaması ASLA reddedilmez: reddedilirse orkestratör sağlıklı düğümü öldürür. */
const NEVER_SHED_PREFIXES = ["/healthz", "/readyz", "/livez", "/metrics"] as const;

/**
 * Yük atmadan önce kaç ARDIŞIK saniye doygun kalınmalı.
 *
 * Yük atma SON ÇAREDİR: normal yükü kuyruk ve eşzamanlılık sınırları taşır
 * (`load-shedding.ts`). Buraya yalnız süreç gerçekten kilitlenmek üzereyken
 * gelinmeli — anlık bir GC tepesi ya da tek bir ağır istek yüzünden değil.
 */
const LOAD_SHED_CONSECUTIVE_SAMPLES = 5;

/**
 * V8 heap sınırı. Süreç ömrü boyunca sabittir; her örnekte yeniden sormaya
 * gerek yok.
 */
let cachedHeapSizeLimit = 0;
function getHeapSizeLimit(): number {
  if (cachedHeapSizeLimit === 0) {
    cachedHeapSizeLimit = getHeapStatistics().heap_size_limit;
  }
  return cachedHeapSizeLimit;
}

function startsWithAny(pathname: string, prefixes: readonly string[]): boolean {
  return prefixes.some(
    (prefix) => pathname === prefix || pathname.startsWith(`${prefix}/`),
  );
}

function routePath(request: FastifyRequest): string {
  // Sorgu dizesi anahtara/sınıflandırmaya girmemeli: `?a=1` ekleyerek farklı
  // kova elde etmenin yolu olurdu.
  const raw = request.url ?? "/";
  const queryIndex = raw.indexOf("?");
  return queryIndex >= 0 ? raw.slice(0, queryIndex) : raw;
}

/**
 * Hız sınırı anahtarı.
 *
 * Token'ın KENDİSİ asla loglanmaz/saklanmaz — yalnız kısaltılmış SHA-256'sı
 * kova adı olur. Kimliksiz istekler IP kovasına düşer.
 */
export function rateLimitKeyGenerator(request: FastifyRequest): string {
  // Başlık DOĞRUDAN okunur; `extractBearerToken` token yoksa `unauthorized()`
  // FIRLATIYOR. Anahtar üreticisi HER istekte çalıştığı için o fırlatma
  // kimliksiz her isteği (healthz, giriş, kayıt) 401'e çeviriyordu — canlıda
  // tam olarak bu oldu. Hız sınırı anahtarı kimlik doğrulaması değildir;
  // burada asla hata fırlatılmaz.
  const header = request.headers.authorization;
  const raw = typeof header === "string" ? header : header?.[0];
  const token = raw?.startsWith("Bearer ")
    ? raw.slice("Bearer ".length).trim()
    : undefined;
  if (token) {
    return `t:${createHash("sha256").update(token).digest("hex").slice(0, 32)}`;
  }
  return `ip:${request.ip}`;
}

/** Rotanın sınıfına göre dakikalık tavan. */
export function rateLimitMaxForRequest(
  env: AppEnv,
  request: FastifyRequest,
): number {
  const pathname = routePath(request);
  if (startsWithAny(pathname, NEVER_SHED_PREFIXES)) {
    return 6_000;
  }
  if (startsWithAny(pathname, PAIRING_ROUTE_PREFIXES)) {
    // Eşleştirme yoklaması meşru ve sıktır; auth tavanının çok üstünde ama
    // yine de sınırlı tutulur.
    return Math.max(env.RATE_LIMIT_AUTH_PER_MINUTE * 8, 240);
  }
  if (startsWithAny(pathname, AUTH_ROUTE_PREFIXES)) {
    return env.RATE_LIMIT_AUTH_PER_MINUTE;
  }
  if (startsWithAny(pathname, EXPENSIVE_ROUTE_PREFIXES)) {
    // GET'ler listeleme/yoklamadır ve ucuzdur; pahalı olan yazan çağrılardır.
    return request.method === "GET"
      ? Math.max(env.RATE_LIMIT_EXPENSIVE_PER_MINUTE * 6, 60)
      : env.RATE_LIMIT_EXPENSIVE_PER_MINUTE;
  }
  return 600;
}

export type ProcessPressureMonitor = {
  saturated: () => boolean;
  snapshot: () => {
    eventLoopLagMs: number;
    heapUsedRatio: number;
    shedding: boolean;
  };
  stop: () => void;
};

/**
 * Olay döngüsü gecikmesi ve heap doluluğunu izler.
 *
 * `monitorEventLoopDelay` çekirdek bir histogram — ek bağımlılık yok, ölçüm
 * maliyeti ihmal edilebilir. Pencere her örnekte sıfırlanır ki geçmiş bir
 * tepe sonsuza kadar yük atmaya sebep olmasın.
 */
export function createProcessPressureMonitor(env: AppEnv): ProcessPressureMonitor {
  const histogram = monitorEventLoopDelay({ resolution: 20 });
  histogram.enable();

  let eventLoopLagMs = 0;
  let heapUsedRatio = 0;
  let saturatedSamples = 0;

  const sample = () => {
    // p99, ortalamadan dürüst: tek uzun blok ortalamada kaybolur ama
    // kullanıcı onu tam olarak hisseder.
    eventLoopLagMs = histogram.percentile(99) / 1e6;
    histogram.reset();

    // HEAP ORANI: kullanılan / SINIR.
    //
    // Önceden `heapUsed / heapTotal` kullanılıyordu ve bu ÖLÇÜM HATASIYDI:
    // V8 `heapTotal`'ı `heapUsed`'ın hemen üstünde tutar, dolayısıyla oran
    // tamamen boştaki bir süreçte bile 0.9+ olur. Canlıda 4 MB kullanım /
    // 2 GB sınır varken oran 0.955 ölçüldü ve sunucu kendini "yoğun" sanıp
    // kullanıcıları geri çevirdi. Gerçek başlık payı yalnız V8'in heap
    // SINIRINA göre anlamlıdır.
    const memory = process.memoryUsage();
    const limit = getHeapSizeLimit();
    heapUsedRatio = limit > 0 ? memory.heapUsed / limit : 0;

    saturatedSamples = isSaturatedNow() ? saturatedSamples + 1 : 0;
  };

  const isSaturatedNow = () =>
    eventLoopLagMs > env.LOAD_SHED_EVENT_LOOP_LAG_MS ||
    heapUsedRatio > env.LOAD_SHED_HEAP_USED_RATIO;

  const timer = setInterval(sample, 1_000);
  // Ölçüm zamanlayıcısı süreci canlı TUTMAMALI.
  timer.unref?.();

  /**
   * SÜREKLİ doygunluk şart: tek bir örnek yetmez.
   *
   * Anlık bir tepe (büyük bir GC, tek bir ağır istek) normal çalışmanın
   * parçası. Tek örneğe bakıp istek reddetmek, sağlıklı bir sunucuyu
   * kullanıcıya "yoğun" gösteriyordu. Ancak birkaç saniye boyunca ARALIKSIZ
   * doygunluk gerçek bir sorundur.
   */
  const saturated = () =>
    env.LOAD_SHED_ENABLED &&
    saturatedSamples >= LOAD_SHED_CONSECUTIVE_SAMPLES;

  return {
    saturated,
    snapshot: () => ({
      eventLoopLagMs: Number(eventLoopLagMs.toFixed(1)),
      heapUsedRatio: Number(heapUsedRatio.toFixed(3)),
      shedding: saturated(),
    }),
    stop: () => {
      clearInterval(timer);
      histogram.disable();
    },
  };
}

/**
 * Doygunlukta yeni İŞ isteklerini reddeder.
 *
 * Sağlık uçları dokunulmaz; yalnız yeni iş girişi kesilir. Böylece kuyruktaki
 * işler bitebilir ve süreç kendini toparlar.
 */
export function registerProcessPressureGuard(
  app: FastifyInstance,
  monitor: ProcessPressureMonitor,
): void {
  app.addHook(
    "onRequest",
    async (request: FastifyRequest, reply: FastifyReply) => {
      const pathname = routePath(request);
      if (startsWithAny(pathname, NEVER_SHED_PREFIXES) || !monitor.saturated()) {
        return;
      }
      request.log.warn(
        { route: pathname, ...monitor.snapshot() },
        "process pressure: request rejected",
      );
      return reply
        .header("Retry-After", "2")
        .code(503)
        .send({
          error: {
            code: "server_overloaded",
            message: "Sunucu şu an yoğun. Birkaç saniye sonra tekrar dene.",
          },
        });
    },
  );
}
