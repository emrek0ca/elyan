import type { FastifyInstance } from "fastify";
import { and, desc, eq, isNull, or } from "drizzle-orm";
import { devices, runtimeConnections } from "../../db/schema.js";

/**
 * HANGİ YETENEK HANGİ CİHAZDA? — cihazlar arası yürütmenin ön koşulu.
 *
 * ÖLÇÜM (2026-08-22):
 *   devices        : ios 129 · macos 48 · linux 6 · darwin 2 · server 1
 *   masaüstü       : `runtime_connections.capabilities` → 102 yetenek beyan ediyor
 *   MOBİL          : eski istemcilerde hiçbir yetenek beyan etmiyor
 *
 * Yani planlayıcı "kamera/konum/bildirim/paylaşım mobilde" bilgisine sahip
 * değil. "Bilgisayarımdaki son faturayı bul ve telefona gönder" gibi bir
 * isteği cihazlara bölememesinin sebebi bu: ikinci cihazın ne yapabildiği
 * hiçbir yerde yazmıyor.
 *
 * İKİ KAYNAK, AÇIK ÖNCELİK
 * ------------------------
 * 1. Çalışma zamanı beyanı (masaüstü bunu yapıyor) — GERÇEK kaynak.
 * 2. İstemci beyanı (mobil register payload'ı) — gerçek mobil yüzey.
 * 3. Platform tabanı (aşağıdaki liste) — eski istemci beyanı yokken kullanılan taban.
 *
 * Taban elle tutulan bir listedir ve bu projede elle tutulan listeler
 * defalarca gerçekle ayrıştı. Bu yüzden: beyan varsa taban HİÇ kullanılmaz,
 * ve taban yalnız platformun kesin olarak sunduğu yüzeyleri içerir
 * (iOS'ta kamera vardır — bu bir tahmin değil). Mobil istemci beyan
 * gönderdiği sürece bu liste o cihaz için ölür.
 */

/** iOS uygulamasının platform gereği sunduğu yüzeyler. */
const IOS_BASELINE_CAPABILITIES = [
  "camera",
  "location",
  "notifications",
  "contacts",
  "share",
  "photo_library",
  "microphone",
  "present_file",
] as const;

export type DeviceCapabilityView = {
  deviceId: string;
  platform: string;
  kind: "desktop" | "mobile" | "server" | "unknown";
  online: boolean;
  capabilities: string[];
  /** Yetenekler nereden geldi — beyan mı, taban mı? */
  source: "runtime_declared" | "client_declared" | "platform_baseline" | "none";
};

/**
 * İKİ AYRI YAZIM, AYNI YETENEK.
 *
 * CANLI ARIZA (görev 4d1a9de6, 2026-08-22 19:18): gölge yerleştirmesi
 * `resolved: 0, unresolved: 2` dedi — `file_search` ve `send_whatsapp_message`
 * hiçbir cihaza yerleştirilemedi. Oysa masaüstü 102 yetenek beyan ediyordu ve
 * içlerinde `file.search` VARDI.
 *
 * Sebep: çalışma zamanı NOKTA ile beyan ediyor (`document.write`,
 * `desktop.operator.observe.screen`), planlar ise ALT ÇİZGİ kullanıyor
 * (`document_write`, `desktop_operator.observe_screen`). İki isimlendirme
 * sözleşmesi, aynı yetenek — bu projenin imza hata sınıfı.
 *
 * Saf nokta↔alt çizgi çevirisi YETMEZ: plan adı `desktop_operator.observe_screen`
 * ikisini birden içeriyor. Bu yüzden her iki ayırıcı da tek bir ayırıcıya
 * indirgenip karşılaştırılıyor.
 */
function canonicalCapabilityKey(value: string): string {
  return value
    .trim()
    .toLowerCase()
    .replace(/[._\s]+/g, ".")
    .replace(/^\.+|\.+$/g, "");
}

function classifyPlatform(platform: string): DeviceCapabilityView["kind"] {
  const normalized = platform.toLowerCase();
  if (normalized === "ios" || normalized === "android") return "mobile";
  if (normalized === "macos" || normalized === "darwin" || normalized === "linux" || normalized === "windows") {
    return "desktop";
  }
  if (normalized === "server") return "server";
  return "unknown";
}

function readDeclaredCapabilities(value: unknown): string[] {
  if (!Array.isArray(value)) return [];
  return value
    .map((item) =>
      typeof item === "string"
        ? item
        : typeof (item as { name?: unknown })?.name === "string"
          ? String((item as { name: string }).name)
          : "",
    )
    .map((item) => item.trim())
    .filter(Boolean);
}

function readClientDeclaredCapabilities(value: unknown): string[] {
  if (!value || typeof value !== "object" || Array.isArray(value)) return [];
  return readDeclaredCapabilities(
    (value as { capabilities?: unknown }).capabilities,
  );
}

type DeviceCapabilityRow = {
  deviceId: unknown;
  platform: unknown;
  capabilities: unknown;
  clientMetadata?: unknown;
  status: unknown;
  heartbeat: unknown;
};

function isUndefinedColumnError(error: unknown): boolean {
  return Boolean(
    typeof error === "object" &&
    error &&
    "code" in error &&
    String(error.code) === "42703",
  );
}

/**
 * Kullanıcının cihazları ve her birinin yapabildikleri.
 *
 * Çevrimdışı cihaz da DÖNER — planlayıcının "yetenek var ama cihaz kapalı"
 * ile "yetenek hiç yok" arasını ayırt etmesi gerekir. İkisini aynı saymak,
 * kullanıcıya "yapamıyorum" demekle "şu an ulaşamıyorum" demeyi karıştırır.
 */
export async function readDeviceCapabilityMap(
  app: FastifyInstance,
  input: { userId: string; deviceId?: string | null },
): Promise<DeviceCapabilityView[]> {
  try {
    const deviceFilter = input.deviceId
      ? and(
          eq(devices.id, input.deviceId),
          or(eq(devices.userId, input.userId), isNull(devices.userId)),
        )
      : eq(devices.userId, input.userId);
    let rows: DeviceCapabilityRow[];
    try {
      rows = await app.db
        .select({
          deviceId: devices.id,
          platform: devices.platform,
          capabilities: runtimeConnections.capabilities,
          clientMetadata: devices.clientMetadata,
          status: runtimeConnections.status,
          heartbeat: runtimeConnections.lastHeartbeatAt,
        })
        .from(devices)
        .leftJoin(
          runtimeConnections,
          eq(runtimeConnections.deviceId, devices.id),
        )
        .where(deviceFilter)
        .orderBy(desc(runtimeConnections.lastHeartbeatAt))
        .limit(50);
    } catch (error) {
      if (!isUndefinedColumnError(error)) throw error;
      app.log?.warn?.(
        "devices.client_metadata migration missing; using runtime-only capability map",
      );
      rows = await app.db
        .select({
          deviceId: devices.id,
          platform: devices.platform,
          capabilities: runtimeConnections.capabilities,
          status: runtimeConnections.status,
          heartbeat: runtimeConnections.lastHeartbeatAt,
        })
        .from(devices)
        .leftJoin(
          runtimeConnections,
          eq(runtimeConnections.deviceId, devices.id),
        )
        .where(deviceFilter)
        .orderBy(desc(runtimeConnections.lastHeartbeatAt))
        .limit(50);
    }

    const byDevice = new Map<string, DeviceCapabilityView>();
    for (const row of rows) {
      const deviceId = String(row.deviceId ?? "");
      if (!deviceId || byDevice.has(deviceId)) continue;
      const platform = String(row.platform ?? "unknown");
      const kind = classifyPlatform(platform);
      const runtimeDeclared = readDeclaredCapabilities(row.capabilities);
      const clientDeclared =
        kind === "mobile"
          ? readClientDeclaredCapabilities(row.clientMetadata)
          : [];
      const declared =
        runtimeDeclared.length > 0 ? runtimeDeclared : clientDeclared;
      const capabilities =
        declared.length > 0
          ? declared
          : kind === "mobile"
            ? [...IOS_BASELINE_CAPABILITIES]
            : [];
      byDevice.set(deviceId, {
        deviceId,
        platform,
        kind,
        online: String(row.status ?? "") === "online",
        capabilities,
        source:
          runtimeDeclared.length > 0
            ? "runtime_declared"
            : clientDeclared.length > 0
              ? "client_declared"
              : capabilities.length > 0
                ? "platform_baseline"
                : "none",
      });
    }
    return [...byDevice.values()];
  } catch (error) {
    app.log?.warn?.(
      { err: error instanceof Error ? error.message : String(error) },
      "device capability map unavailable",
    );
    return [];
  }
}

export type CapabilityPlacement = {
  capability: string;
  deviceId: string;
  kind: DeviceCapabilityView["kind"];
  online: boolean;
  source: DeviceCapabilityView["source"];
};

/**
 * Bu yetenek NEREDE çalışabilir?
 *
 * Çevrimiçi cihaz önce gelir; ama çevrimdışı seçenek de döner ki çağıran
 * "hiç yok" ile "şu an kapalı" arasını ayırabilsin.
 */
export function placeCapability(
  map: DeviceCapabilityView[],
  capability: string,
): CapabilityPlacement[] {
  const needle = capability.trim();
  if (!needle) return [];
  const key = canonicalCapabilityKey(needle);
  return map
    .filter((device) =>
      device.capabilities.some(
        (capability) => canonicalCapabilityKey(capability) === key,
      ),
    )
    .sort((left, right) => Number(right.online) - Number(left.online))
    .map((device) => ({
      capability: needle,
      deviceId: device.deviceId,
      kind: device.kind,
      online: device.online,
      source: device.source,
    }));
}
