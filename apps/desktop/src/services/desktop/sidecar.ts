import { invoke } from "@tauri-apps/api/core";

import { DEFAULT_BASE_URL } from "@/services/api/client";
import type { SidecarHealth } from "@/types/domain";

const DEFAULT_PORT = 18789;
const FALLBACK_PORTS = [18789];

function defaultHealth(overrides: Partial<SidecarHealth> = {}): SidecarHealth {
  return {
    status: "offline",
    managed: false,
    port: DEFAULT_PORT,
    runtimeUrl: DEFAULT_BASE_URL,
    retries: 0,
    ...overrides,
  };
}

function isTauriRuntime() {
  if (typeof window === "undefined") {
    return false;
  }
  return "__TAURI_INTERNALS__" in (window as unknown as Record<string, unknown>);
}

function buildCandidateBaseUrls() {
  const urls = new Set<string>();
  const normalized = DEFAULT_BASE_URL.trim().replace(/\/+$/, "");
  if (normalized) {
    urls.add(normalized);
  }
  for (const port of FALLBACK_PORTS) {
    urls.add(`http://127.0.0.1:${port}`);
    urls.add(`http://localhost:${port}`);
  }
  return Array.from(urls);
}

async function probeRuntimeHealth(): Promise<SidecarHealth> {
  const candidates = buildCandidateBaseUrls();
  for (const baseUrl of candidates) {
    try {
      const response = await fetch(`${baseUrl}/healthz`, {
        method: "GET",
        headers: { Accept: "application/json" },
      });
      if (!response.ok) {
        continue;
      }
      const payload = (await response.json().catch(() => ({}))) as Record<string, unknown>;
      const protocolVersion = String(payload.protocol_version || payload.protocolVersion || "elyan-cowork-v1");
      const runtimeVersion = String(payload.version || payload.app_version || payload.appVersion || "");
      const adminToken = String(payload.admin_token || payload.adminToken || "") || null;
      const readiness = (payload.readiness as Record<string, unknown> | undefined) || {};
      const launchBlockers = Array.isArray(readiness.launch_blockers)
        ? readiness.launch_blockers.map((item) => String(item || "").trim()).filter(Boolean)
        : [];
      const launchReady = Boolean(readiness.launch_ready ?? payload.ok);
      const runtimeReady = Boolean(readiness.elyan_ready ?? launchReady);
      const modelLaneReady = Boolean(readiness.model_lane_ready ?? false);
      const runtimeUrl = baseUrl.trim().replace(/\/+$/, "");
      const port = Number(runtimeUrl.split(":").pop() || DEFAULT_PORT) || DEFAULT_PORT;
      const compatible = protocolVersion === "elyan-cowork-v1";
      const healthy = Boolean(launchReady && compatible);
      return {
        status: healthy ? "healthy" : "degraded",
        managed: false,
        port,
        runtimeUrl,
        retries: 0,
        runtimeVersion,
        runtimeProtocolVersion: protocolVersion,
        expectedProtocolVersion: "elyan-cowork-v1",
        compatible,
        compatibilityReason: compatible
          ? (launchReady ? null : "launch_blocked")
          : "protocol_mismatch",
        runtimeReady,
        modelLaneReady,
        launchReady,
        launchBlockers,
        healthStatus: String(payload.health_status || payload.healthStatus || ""),
        lastReadyAt: healthy ? new Date().toISOString() : null,
        adminToken,
        lastError: healthy ? null : (launchBlockers.length > 0 ? launchBlockers.join("; ") : "Local runtime not ready"),
      };
    } catch {
      continue;
    }
  }
  return defaultHealth({
    status: "offline",
    lastError: "Local runtime unavailable",
    compatible: false,
    compatibilityReason: "runtime_offline",
    runtimeReady: false,
    modelLaneReady: false,
    launchReady: false,
    launchBlockers: ["Local runtime unavailable"],
  });
}

async function invokeOrFallback<T>(command: string, args: Record<string, unknown> | undefined, fallback: T): Promise<T> {
  if (!isTauriRuntime()) {
    return fallback;
  }
  try {
    return await invoke<T>(command, args);
  } catch {
    return fallback;
  }
}

export const sidecarBridge = {
  async bootRuntime() {
    if (!isTauriRuntime()) {
      return probeRuntimeHealth();
    }
    return invokeOrFallback<SidecarHealth>("boot_runtime", undefined, await probeRuntimeHealth());
  },
  stopRuntime() {
    return invokeOrFallback<SidecarHealth>("stop_runtime", undefined, defaultHealth({ status: "stopped" }));
  },
  restartRuntime() {
    return invokeOrFallback<SidecarHealth>("restart_runtime", undefined, defaultHealth({ status: "starting", managed: true }));
  },
  async getRuntimeHealth() {
    if (!isTauriRuntime()) {
      return probeRuntimeHealth();
    }
    return invokeOrFallback<SidecarHealth>("get_runtime_health", undefined, await probeRuntimeHealth());
  },
  getRuntimeLogs() {
    return invokeOrFallback<string[]>("get_runtime_logs", undefined, []);
  },
  exportRuntimeLogs(path?: string) {
    return invokeOrFallback<string>("export_runtime_logs", { path }, "");
  },
  openArtifact(path: string) {
    return invokeOrFallback<boolean>("open_artifact", { path }, false);
  },
  revealInFolder(path: string) {
    return invokeOrFallback<boolean>("reveal_in_folder", { path }, false);
  },
  openExternalUrl(url: string) {
    return invokeOrFallback<boolean>("open_external_url", { url }, false);
  },
};
