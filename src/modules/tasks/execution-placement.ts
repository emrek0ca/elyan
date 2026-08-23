import type { FastifyInstance } from "fastify";
import {
  placeCapability,
  readDeviceCapabilityMap,
  type DeviceCapabilityView,
} from "../devices/device-capability-map.js";
import type { DesktopWorkOrderStep } from "./desktop-work-order.js";
import type { ExecutionDevice, ExecutionStep } from "./execution-step.js";

/**
 * YERLEŞTİRME — hangi adım hangi cihazda çalışacak? (Notion §5)
 *
 * Koordinatörün sorması gereken sıra:
 *   gerekli capability → hangi cihazlarda var → veri nerede → izin var mı
 *   → cihaz açık mı → en iyi hedef
 *
 * Bu modül o zincirin ilk üç halkasını çözer ve kararı GÖRÜNÜR kılar. Ölçüm
 * hazır değilse plan gölgede kalır; yalnızca gerçek çalışma zamanı beyanı ile
 * tüm adımlar masaüstüne bağlandığında yürütme bağına dönüşür.
 *
 * GÖLGE → BAĞLI
 * ------------
 * Eski `planPreview.steps` yolu geriye dönük uyumluluk için korunur. Yeni
 * `executionSteps` yalnız fail-closed yerleştirme kapısından geçen planlarda
 * runtime'a verilir; böylece cihaz kararı ölçülmeden yürütme makinesi
 * değişmez.
 */

export type StepPlacement = {
  stepId: string;
  capability: string;
  device?: ExecutionDevice;
  deviceId?: string;
  online?: boolean;
  /** Karar nasıl verildi — ölçüm ve teşhis için. */
  basis:
    | "declared_online"
    | "declared_offline"
    | "baseline_online"
    | "baseline_offline"
    | "unresolved";
};

export type ExecutionPlacementSummary = {
  total: number;
  resolved: number;
  unresolved: number;
  offline: number;
  byDevice: Record<string, number>;
};

export type ExecutionPlacementSnapshot = {
  mode: "shadow" | "bound";
  resolvedAt: string;
  summary: ExecutionPlacementSummary;
  unresolvedCapabilities: string[];
};

function toExecutionDevice(kind: DeviceCapabilityView["kind"]): ExecutionDevice | undefined {
  if (kind === "desktop") return "desktop";
  if (kind === "mobile") return "mobile";
  if (kind === "server") return "control-plane";
  return undefined;
}

/**
 * Adımları cihazlara yerleştir.
 *
 * ÇÖZÜLEMEYEN ADIM UYDURULMAZ. `device` boş bırakılır ve `basis: "unresolved"`
 * yazılır. Bir yeteneği rastgele bir cihaza koymak, kullanıcının işini yanlış
 * makinede çalıştırmaktır — çözememekten kötüdür.
 */
export async function placeExecutionSteps(
  app: FastifyInstance,
  input: {
    userId: string;
    targetDeviceId: string;
    steps: DesktopWorkOrderStep[];
  },
): Promise<{
  steps: ExecutionStep[];
  placements: StepPlacement[];
  map: DeviceCapabilityView[];
}> {
  const map = await readDeviceCapabilityMap(app, {
    userId: input.userId,
    deviceId: input.targetDeviceId,
  });
  const placements: StepPlacement[] = [];
  const steps: ExecutionStep[] = [];

  for (const step of input.steps) {
    const candidates = placeCapability(map, step.capability);
    const best = candidates[0];
    const device = best ? toExecutionDevice(best.kind) : undefined;
    const basis: StepPlacement["basis"] = !best
      ? "unresolved"
      : best.source === "runtime_declared" || best.source === "client_declared"
        ? best.online
          ? "declared_online"
          : "declared_offline"
        : best.online
          ? "baseline_online"
          : "baseline_offline";

    placements.push({
      stepId: step.id,
      capability: step.capability,
      ...(device ? { device } : {}),
      ...(best ? { deviceId: best.deviceId, online: best.online } : {}),
      basis,
    });
    steps.push({
      stepId: step.id,
      capability: step.capability,
      ...(device ? { device } : {}),
      ...(step.dependsOn && step.dependsOn.length > 0 ? { dependsOn: step.dependsOn } : {}),
      ...(step.args !== undefined ? { input: step.args } : {}),
      ...(step.resourceScope && step.resourceScope.length > 0
        ? { resourceScope: step.resourceScope }
        : {}),
      ...(step.forEach ? { forEach: step.forEach } : {}),
    });
  }

  return { steps, placements, map };
}

/** Ölçüm özeti — yerleştirme ne kadar işe yarıyor? */
export function summarizePlacements(
  placements: StepPlacement[],
): ExecutionPlacementSummary {
  const byDevice: Record<string, number> = {};
  let resolved = 0;
  let offline = 0;
  for (const placement of placements) {
    if (placement.basis === "unresolved") continue;
    resolved += 1;
    if (placement.online === false) offline += 1;
    const key = placement.device ?? "unknown";
    byDevice[key] = (byDevice[key] ?? 0) + 1;
  }
  return {
    total: placements.length,
    resolved,
    unresolved: placements.length - resolved,
    offline,
    byDevice,
  };
}

/**
 * Persistable, bounded shadow evidence for a work-order plan.
 *
 * The full device map stays local to this decision. Only the counts and the
 * unresolved capability names travel with the plan, so the control plane does
 * not copy unrelated device metadata into the task payload.
 */
export function buildPlacementSnapshot(
  placements: StepPlacement[],
  resolvedAt = new Date().toISOString(),
  mode: ExecutionPlacementSnapshot["mode"] = "shadow",
): ExecutionPlacementSnapshot {
  return {
    mode,
    resolvedAt,
    summary: summarizePlacements(placements),
    unresolvedCapabilities: placements
      .filter((placement) => placement.basis === "unresolved")
      .map((placement) => placement.capability)
      .slice(0, 32),
  };
}

/**
 * Masaüstü yürütmesine bağlanmak için gereken minimum ölçüm kanıtı.
 *
 * `platform_baseline` yalnız cihazın teorik yüzeyini anlatır; `client_declared`
 * mobil yürütme için henüz readiness/izin el sıkışması değildir. Bu nedenle
 * gerçek desktop dispatch yalnız çalışan masaüstü runtime'ının beyanına
 * bağlanır.
 */
export function isDesktopPlacementReady(input: {
  placements: StepPlacement[];
}): boolean {
  return (
    input.placements.length > 0 &&
    input.placements.every(
      (placement) =>
        placement.basis === "declared_online" &&
        placement.device === "desktop" &&
        placement.online === true,
    )
  );
}

/**
 * Bu plan gönderilebilir mi?
 *
 * CANLI ARIZA (görev 4d1a9de6): plan iki adımdı —
 *   1. file_search             → çalıştı
 *   2. send_whatsapp_message   → HİÇBİR CİHAZDA YOK → FILE_NOT_FOUND ile öldü
 * Yerleştirme bunu ÖNCEDEN biliyordu (`unresolved`), ama kimse okumuyordu.
 *
 * "Sessiz düşüş yasak" kuralı yazıcı gövdesi için uygulanmıştı; aynısı burada
 * da geçerli: hiçbir cihazda çalışamayacak bir adım içeren plan gönderilmez.
 *
 * KAPI YALNIZ BİLGİ VARKEN KONUŞUR. Hiçbir cihaz yetenek beyan etmemişse
 * (bağlantı yok, eski istemci) her adım "unresolved" görünür; o durumda
 * susmak zorunludur — yoksa bilgi eksikliği yüzünden tüm görevler ölür.
 */
export function unplaceableSteps(input: {
  placements: StepPlacement[];
  map: DeviceCapabilityView[];
}): StepPlacement[] {
  // Mobile declarations are currently shadow evidence only. They are bounded
  // by the server vocabulary, but do not yet include a permission/readiness
  // handshake that could authorize real mobile execution.
  const hasTrustedRuntimeCapabilities = input.map.some(
    (device) => device.source === "runtime_declared" && device.capabilities.length > 0,
  );
  if (!hasTrustedRuntimeCapabilities) return [];
  return input.placements.filter((placement) => placement.basis === "unresolved");
}
