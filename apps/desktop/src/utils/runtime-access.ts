import type { RuntimeConnectionState, SidecarHealth } from "@/types/domain";

export function hasRuntimeWriteAccess(connectionState: RuntimeConnectionState, health: SidecarHealth) {
  return connectionState === "connected" && Boolean(health.adminToken) && health.compatible !== false;
}

export function getRuntimeGateReason(connectionState: RuntimeConnectionState, health: SidecarHealth) {
  if (connectionState !== "connected") {
    return "Runtime henüz hazır değil.";
  }
  if (health.compatible === false) {
    return health.compatibilityReason || "Desktop ve runtime sürümü uyumsuz.";
  }
  if (!health.adminToken) {
    return "Yazma aksiyonları için admin token henüz alınamadı.";
  }
  return "";
}
