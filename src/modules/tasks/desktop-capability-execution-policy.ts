import {
  speechActAllowsExecution,
  type SpeechAct,
} from "../../core/understanding/speech-act.js";
import {
  DESKTOP_CAPABILITY_MANIFEST,
  type DesktopCapabilityManifestEntry,
} from "./desktop-capability-manifest.js";

export type DesktopCapabilityExecutionAuthority = "desktop" | "hybrid";

export type DesktopCapabilityExecutionPolicy = {
  capability: string;
  authority: DesktopCapabilityExecutionAuthority;
  privacyClass: string;
  sideEffectClass: DesktopCapabilityManifestEntry["sideEffectClass"];
  requiresApproval: boolean;
  questionSafeObservation: boolean;
  fallbackExecutionEligible: boolean;
};

const manifestByName = new Map(
  DESKTOP_CAPABILITY_MANIFEST.map((entry) => [entry.name, entry] as const),
);

export function resolveDesktopCapabilityExecutionPolicy(
  capability: string,
): DesktopCapabilityExecutionPolicy | null {
  const name = String(capability ?? "").trim();
  const entry = manifestByName.get(name);
  if (!entry) return null;
  const authority: DesktopCapabilityExecutionAuthority =
    entry.executionAuthority === "desktop" ? "desktop" : "hybrid";
  return {
    capability: name,
    authority,
    privacyClass: entry.privacyClass,
    sideEffectClass: entry.sideEffectClass,
    requiresApproval: entry.requiresApproval,
    questionSafeObservation: entry.questionSafeObservation,
    fallbackExecutionEligible: entry.fallbackExecutionEligible,
  };
}

export function isDesktopExecutionCapability(capability: string): boolean {
  return resolveDesktopCapabilityExecutionPolicy(capability)?.authority === "desktop";
}

/**
 * Speech act decides whether the user requests work; the capability contract
 * decides whether a question itself requires a live observation. A question
 * may therefore execute only a known, approval-free desktop read. It can
 * never turn a write/destructive tool into an action.
 */
export function capabilityAllowsSpeechActExecution(
  act: SpeechAct | null | undefined,
  capability: string,
  options: { desktopRouteConfirmed?: boolean } = {},
): boolean {
  const policy = resolveDesktopCapabilityExecutionPolicy(capability);
  if (!policy || policy.authority !== "desktop") return false;
  if (speechActAllowsExecution(act)) {
    if (
      options.desktopRouteConfirmed !== true &&
      !policy.fallbackExecutionEligible
    ) {
      return false;
    }
    if (
      (act === "confirmation" || act === "correction") &&
      options.desktopRouteConfirmed !== true
    ) {
      return false;
    }
    return true;
  }
  return (
    act === "question" &&
    policy.questionSafeObservation &&
    policy.requiresApproval === false &&
    (policy.sideEffectClass === "none" || policy.sideEffectClass === "read") &&
    (options.desktopRouteConfirmed === true || policy.fallbackExecutionEligible)
  );
}
