import { apiClient } from "@/services/api/client";
import { sidecarBridge } from "@/services/desktop/sidecar";
import type { SidecarHealth } from "@/types/domain";

function normalizeRuntimeUrl(health: SidecarHealth) {
  return health.runtimeUrl?.trim() || apiClient.getBaseUrl();
}

function syncRuntimeHeaders(health: SidecarHealth) {
  apiClient.setBaseUrl(normalizeRuntimeUrl(health));
}

export class SidecarSupervisor {
  async boot() {
    const health = await sidecarBridge.bootRuntime();
    syncRuntimeHeaders(health);
    return health;
  }

  async getHealth() {
    const health = await sidecarBridge.getRuntimeHealth();
    syncRuntimeHeaders(health);
    return health;
  }

  async restart() {
    const health = await sidecarBridge.restartRuntime();
    syncRuntimeHeaders(health);
    return health;
  }

  async stop() {
    const health = await sidecarBridge.stopRuntime();
    syncRuntimeHeaders(health);
    return health;
  }

  async getLogs() {
    return sidecarBridge.getRuntimeLogs();
  }

  async exportLogs(path?: string) {
    return sidecarBridge.exportRuntimeLogs(path);
  }

  async openArtifact(path: string) {
    return sidecarBridge.openArtifact(path);
  }

  async revealInFolder(path: string) {
    return sidecarBridge.revealInFolder(path);
  }

  async openExternalUrl(url: string) {
    return sidecarBridge.openExternalUrl(url);
  }
}

export const sidecarSupervisor = new SidecarSupervisor();
