import { invoke } from "@tauri-apps/api/core";

import { DEFAULT_BASE_URL } from "@/services/api/client";
import type { SidecarHealth } from "@/types/domain";

const DEFAULT_PORT = 18789;

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
  bootRuntime() {
    return invokeOrFallback<SidecarHealth>(
      "boot_runtime",
      undefined,
      defaultHealth({ status: "error", managed: false, lastError: "Managed runtime unavailable" }),
    );
  },
  stopRuntime() {
    return invokeOrFallback<SidecarHealth>("stop_runtime", undefined, defaultHealth({ status: "stopped" }));
  },
  restartRuntime() {
    return invokeOrFallback<SidecarHealth>("restart_runtime", undefined, defaultHealth({ status: "starting", managed: true }));
  },
  getRuntimeHealth() {
    return invokeOrFallback<SidecarHealth>(
      "get_runtime_health",
      undefined,
      defaultHealth({ status: "offline", managed: false, lastError: "Managed runtime unavailable" }),
    );
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
