import type { RuntimeConnectionState, SidecarHealth } from "@/types/domain";

export function hasRuntimeWriteAccess(connectionState: RuntimeConnectionState, health: SidecarHealth) {
  return connectionState === "connected" && health.compatible !== false && health.launchReady !== false;
}

export function getRuntimeGateReason(connectionState: RuntimeConnectionState, health: SidecarHealth) {
  if (connectionState !== "connected") {
    return "Runtime henüz hazır değil.";
  }
  if (health.compatible === false) {
    return health.compatibilityReason || "Desktop ve runtime sürümü uyumsuz.";
  }
  if (health.launchReady === false) {
    if (Array.isArray(health.launchBlockers) && health.launchBlockers.length > 0) {
      return health.launchBlockers.join(" · ");
    }
    return "Gateway launch gate henüz tamamlanmadı.";
  }
  return "";
}
