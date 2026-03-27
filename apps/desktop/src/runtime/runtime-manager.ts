import type { RuntimeConnectionState, SidecarHealth } from "@/types/domain";
import { sidecarSupervisor } from "@/runtime/sidecar-supervisor";

export function getRuntimeConnectionState(health: SidecarHealth): RuntimeConnectionState {
  switch (health.status) {
    case "healthy":
      return "connected";
    case "starting":
      return "booting";
    case "degraded":
      return "reconnecting";
    case "error":
      return "error";
    default:
      return "offline";
  }
}

export class RuntimeManager {
  bootRuntime() {
    return sidecarSupervisor.boot();
  }

  getRuntimeHealth() {
    return sidecarSupervisor.getHealth();
  }

  restartRuntime() {
    return sidecarSupervisor.restart();
  }

  stopRuntime() {
    return sidecarSupervisor.stop();
  }

  getRuntimeLogs() {
    return sidecarSupervisor.getLogs();
  }

  openArtifact(path: string) {
    return sidecarSupervisor.openArtifact(path);
  }

  revealInFolder(path: string) {
    return sidecarSupervisor.revealInFolder(path);
  }

  openExternalUrl(url: string) {
    return sidecarSupervisor.openExternalUrl(url);
  }
}

export const runtimeManager = new RuntimeManager();
