import type { CapabilityDirectorySnapshot } from '@/core/capabilities';

export type OptimizationStatusSnapshot = {
  ready: boolean;
  capabilityId: 'optimization_solve';
  bridgeToolId: 'optimization_solve';
  skillId: 'optimization_decision';
  capabilityReady: boolean;
  bridgeToolReady: boolean;
  skillReady: boolean;
  demoModes: Array<'assignment' | 'resource-allocation'>;
  summary: string;
  guidance: string[];
};

function isEnabledCapability(snapshot: CapabilityDirectorySnapshot, capabilityId: string) {
  return snapshot.capabilities.some((entry) => entry.id === capabilityId && entry.enabled);
}

function isEnabledBridgeTool(snapshot: CapabilityDirectorySnapshot, bridgeToolId: string) {
  return snapshot.local.bridgeTools.some((entry) => entry.id === bridgeToolId && entry.enabled);
}

function isEnabledSkill(snapshot: CapabilityDirectorySnapshot, skillId: string) {
  return snapshot.skills.builtIn.some((skill) => skill.id === skillId && skill.enabled);
}

export function buildOptimizationStatusSnapshot(snapshot: CapabilityDirectorySnapshot): OptimizationStatusSnapshot {
  const capabilityReady = isEnabledCapability(snapshot, 'optimization_solve');
  const bridgeToolReady = isEnabledBridgeTool(snapshot, 'optimization_solve');
  const skillReady = isEnabledSkill(snapshot, 'optimization_decision');
  const ready = capabilityReady && bridgeToolReady && skillReady;
  const missingParts = [
    !capabilityReady ? 'capability' : undefined,
    !bridgeToolReady ? 'bridge tool' : undefined,
    !skillReady ? 'skill' : undefined,
  ].filter(Boolean) as string[];

  return {
    ready,
    capabilityId: 'optimization_solve',
    bridgeToolId: 'optimization_solve',
    skillId: 'optimization_decision',
    capabilityReady,
    bridgeToolReady,
    skillReady,
    demoModes: ['assignment', 'resource-allocation'],
    summary:
      missingParts.length === 0
        ? 'Optimization lane is ready: local capability, bridge tool, and decision skill are aligned.'
        : `Optimization lane is partial: missing ${missingParts.join(', ')}.`,
    guidance: [
      'Keep the stack honest: classical and quantum-inspired, not real quantum hardware.',
      'Prefer auditable model, QUBO, solver comparison, and decision report output.',
      'Use assignment and resource-allocation demos when a quick local verification is needed.',
    ],
  };
}
