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

// ── Elyan state types ───────────────────────────────────────────────────────

export interface ElyanAgentActivity {
  id: string;
  agent: string;
  action: string;
  status: "running" | "done" | "error";
  ts: number;
}

export interface ElyanSystemHealth {
  cpu: number;
  batteryPct: number;
  charging: boolean;
  activeModel: string;
}

export interface ElyanChannelStatus {
  telegram: boolean;
  whatsapp: boolean;
  imessage: boolean;
  desktop: boolean;
}

const MAX_ACTIVITIES = 50; // keep last N events in memory

// ── Store type ───────────────────────────────────────────────────────────────

type RuntimeStore = {
  connectionState: RuntimeConnectionState;
  sidecarHealth: SidecarHealth;
  setSidecarHealth: (health: SidecarHealth) => void;

  // Elyan live state
  elyanActivities: ElyanAgentActivity[];
  elyanChannelStatus: ElyanChannelStatus;
  elyanSystemHealth: ElyanSystemHealth;
  pushElyanActivity: (activity: ElyanAgentActivity) => void;
  updateElyanActivity: (id: string, updates: Partial<ElyanAgentActivity>) => void;
  setElyanChannelStatus: (updates: Partial<ElyanChannelStatus>) => void;
  setElyanSystemHealth: (updates: Partial<ElyanSystemHealth>) => void;
};

export const useRuntimeStore = create<RuntimeStore>((set) => ({
  connectionState: "offline",
  sidecarHealth: defaultSidecarHealth,
  setSidecarHealth: (sidecarHealth) =>
    set({
      sidecarHealth,
      connectionState: getRuntimeConnectionState(sidecarHealth),
    }),

  // Elyan defaults
  elyanActivities: [],
  elyanChannelStatus: { telegram: false, whatsapp: false, imessage: false, desktop: false },
  elyanSystemHealth: { cpu: 0, batteryPct: 100, charging: true, activeModel: "" },

  pushElyanActivity: (activity) =>
    set((state) => ({
      elyanActivities: [...state.elyanActivities, activity].slice(-MAX_ACTIVITIES),
    })),

  updateElyanActivity: (id, updates) =>
    set((state) => ({
      elyanActivities: state.elyanActivities.map((a) =>
        a.id === id ? { ...a, ...updates } : a
      ),
    })),

  setElyanChannelStatus: (updates) =>
    set((state) => ({
      elyanChannelStatus: { ...state.elyanChannelStatus, ...updates },
    })),

  setElyanSystemHealth: (updates) =>
    set((state) => ({
      elyanSystemHealth: { ...state.elyanSystemHealth, ...updates },
    })),
}));
