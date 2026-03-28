import { create } from "zustand";

import { DEFAULT_BASE_URL } from "@/services/api/client";
import { getRuntimeConnectionState } from "@/runtime/runtime-manager";
import type { RuntimeConnectionState, SidecarHealth } from "@/types/domain";

export const defaultSidecarHealth: SidecarHealth = {
  status: "offline",
  managed: false,
  port: 18789,
  runtimeUrl: DEFAULT_BASE_URL,
  retries: 0,
  desktopVersion: "0.1.0",
  expectedProtocolVersion: "elyan-cowork-v1",
  compatible: false,
};

type RuntimeStore = {
  connectionState: RuntimeConnectionState;
  sidecarHealth: SidecarHealth;
  setSidecarHealth: (health: SidecarHealth) => void;
};

export const useRuntimeStore = create<RuntimeStore>((set) => ({
  connectionState: "offline",
  sidecarHealth: defaultSidecarHealth,
  setSidecarHealth: (sidecarHealth) =>
    set({
      sidecarHealth,
      connectionState: getRuntimeConnectionState(sidecarHealth),
    }),
}));
