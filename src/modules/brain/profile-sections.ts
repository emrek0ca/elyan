import type { RuntimeCapabilitySummary } from "../runtime/capabilities.js";
import type { SharedBrainModelResolution } from "./model-resolution.js";

export type BrainProfileSectionsInput = {
  serverTargetDeviceId: string | null;
  serverBrainName: string;
  runtimeProvider: string;
  runtimeReady: boolean;
  runtimeCapabilitySummary: RuntimeCapabilitySummary | null;
  desktopAvailable: boolean;
  mobileAvailable: boolean;
  connectedDesktopDevices: number;
  inferenceReady: boolean;
  isChatUsable: boolean;
  modelMode: "base" | "adapted";
  trainingState: "cold" | "base_serving" | "training" | "adapted";
  warmupJobId: string | null;
  activeSharedModelId: string | null;
  activeUserModelId: string | null;
  activeSharedJobId: string | null;
  activeSharedJobStatus: string | null;
  safeLearningEvents: number;
  readyDatasets: number;
  queuedJobs: number;
  runningJobs: number;
  routingSignals: number;
  bridgeSignals: number;
  totalRoutingSignals: number;
  routingQualityScore: number;
  routingQualityState: string;
  bridgeReadiness: boolean;
  readySharedModelCount: number;
  configuredBaseModel: string;
  resolvedBaseModel: string | null;
  resolvedBaseModelSource: SharedBrainModelResolution["resolvedBaseModelSource"];
  availableModels: string[];
};

export function buildBrainProfileSections(input: BrainProfileSectionsInput) {
  return {
    runtime: {
      provider: input.runtimeProvider,
      ready: input.runtimeReady,
      sharedBrainDeviceId: input.serverTargetDeviceId,
      sharedBrainName: input.serverBrainName,
      sharedBrainCapabilitySummary: input.runtimeCapabilitySummary,
      connectedDesktopDevices: input.connectedDesktopDevices,
      desktopAvailable: input.desktopAvailable,
      mobileAvailable: input.mobileAvailable,
      bridgeReadiness: input.bridgeReadiness,
    },
    model: {
      configuredBaseModel: input.configuredBaseModel,
      resolvedBaseModel: input.resolvedBaseModel,
      resolvedBaseModelSource: input.resolvedBaseModelSource,
      availableModels: input.availableModels,
      modelMode: input.modelMode,
      trainingState: input.trainingState,
      inferenceReady: input.inferenceReady,
      isChatUsable: input.isChatUsable,
      activeSharedModelId: input.activeSharedModelId,
      activeUserModelId: input.activeUserModelId,
      warmupJobId: input.warmupJobId,
      activeSharedJobId: input.activeSharedJobId,
      activeSharedJobStatus: input.activeSharedJobStatus,
      readySharedModelCount: input.readySharedModelCount,
    },
    routing: {
      mode: "desktop_first_then_server_brain" as const,
      chat: "server_brain_first" as const,
      task: "desktop_first_when_available" as const,
      desktopAvailable: input.desktopAvailable,
      mobileAvailable: input.mobileAvailable,
      connectedDesktopDevices: input.connectedDesktopDevices,
      bridgeReadiness: input.bridgeReadiness,
      runtimeReady: input.runtimeReady,
      inferenceReady: input.inferenceReady,
      routingSignals: input.routingSignals,
      bridgeSignals: input.bridgeSignals,
      totalRoutingSignals: input.totalRoutingSignals,
      routingQualityScore: input.routingQualityScore,
      routingQualityState: input.routingQualityState,
    },
    learning: {
      safeLearningEvents: input.safeLearningEvents,
      readyDatasets: input.readyDatasets,
      queuedJobs: input.queuedJobs,
      runningJobs: input.runningJobs,
    },
  };
}
