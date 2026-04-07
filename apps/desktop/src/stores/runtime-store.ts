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

// ── Jarvis state types ───────────────────────────────────────────────────────

export interface JarvisAgentActivity {
  id: string;
  agent: string;
  action: string;
  status: "running" | "done" | "error";
  ts: number;
}

export interface JarvisSystemHealth {
  cpu: number;
  batteryPct: number;
  charging: boolean;
  activeModel: string;
}

export interface JarvisChannelStatus {
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

  // Jarvis live state
  jarvisActivities: JarvisAgentActivity[];
  jarvisChannelStatus: JarvisChannelStatus;
  jarvisSystemHealth: JarvisSystemHealth;
  pushJarvisActivity: (activity: JarvisAgentActivity) => void;
  updateJarvisActivity: (id: string, updates: Partial<JarvisAgentActivity>) => void;
  setJarvisChannelStatus: (updates: Partial<JarvisChannelStatus>) => void;
  setJarvisSystemHealth: (updates: Partial<JarvisSystemHealth>) => void;
};

export const useRuntimeStore = create<RuntimeStore>((set) => ({
  connectionState: "offline",
  sidecarHealth: defaultSidecarHealth,
  setSidecarHealth: (sidecarHealth) =>
    set({
      sidecarHealth,
      connectionState: getRuntimeConnectionState(sidecarHealth),
    }),

  // Jarvis defaults
  jarvisActivities: [],
  jarvisChannelStatus: { telegram: false, whatsapp: false, imessage: false, desktop: false },
  jarvisSystemHealth: { cpu: 0, batteryPct: 100, charging: true, activeModel: "" },

  pushJarvisActivity: (activity) =>
    set((state) => ({
      jarvisActivities: [...state.jarvisActivities, activity].slice(-MAX_ACTIVITIES),
    })),

  updateJarvisActivity: (id, updates) =>
    set((state) => ({
      jarvisActivities: state.jarvisActivities.map((a) =>
        a.id === id ? { ...a, ...updates } : a
      ),
    })),

  setJarvisChannelStatus: (updates) =>
    set((state) => ({
      jarvisChannelStatus: { ...state.jarvisChannelStatus, ...updates },
    })),

  setJarvisSystemHealth: (updates) =>
    set((state) => ({
      jarvisSystemHealth: { ...state.jarvisSystemHealth, ...updates },
    })),
}));
