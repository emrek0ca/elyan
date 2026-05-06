import type { CapabilityApprovalLevel, CapabilityRiskLevel, CapabilityDirectorySnapshot } from '@/core/capabilities';
import type { ModelInfo } from '@/types/provider';
import type { OperatorStatusSnapshot } from '@/core/operator/status';

export type RuntimeRegistrySectionSource = 'local' | 'cached' | 'mixed';
export type RuntimeRegistrySectionStatus = 'healthy' | 'degraded' | 'unknown';

export type RuntimeRegistrySectionBase = {
  status: RuntimeRegistrySectionStatus;
  enabled: boolean;
  source: RuntimeRegistrySectionSource;
  risk: CapabilityRiskLevel;
  approvalRequirement: CapabilityApprovalLevel;
  live: boolean;
  cached: boolean;
  lastError?: string;
};

type RuntimeRegistrySection<TCounts, TLatest> = RuntimeRegistrySectionBase & {
  counts: TCounts;
  latest?: TLatest;
};

export type RuntimeRegistryRunLatest = {
  id: string;
  title: string;
  mode: string;
  status: string;
  updatedAt: string;
  reasoningDepth: string;
  approvalCount: number;
  pendingApprovals: number;
};

export type RuntimeRegistryApprovalLatest = {
  id: string;
  title: string;
  status: string;
  approvalLevel: string;
  riskLevel: string;
  requestedAt: string;
};

export type RuntimeRegistrySkillLatest = {
  id: string;
  title: string;
  enabled: boolean;
  approvalLevel: string;
  riskLevel: string;
};

export type RuntimeRegistryMcpLatest = {
  id: string;
  title: string;
  state: string;
  reason: string;
};

export type RuntimeRegistryModelLatest = {
  id: string;
  title: string;
  provider: string;
  type: string;
};

export type RuntimeRegistrySnapshot = {
  status: RuntimeRegistrySectionStatus;
  summary: {
    runCount: number;
    approvalCount: number;
    pendingApprovalCount: number;
    skillCount: number;
    enabledSkillCount: number;
    mcpServerCount: number;
    mcpEnabledServerCount: number;
    mcpLiveServerCount: number;
    modelCount: number;
    localModelCount: number;
    cloudModelCount: number;
  };
  runs: RuntimeRegistrySection<
    {
      total: number;
      blocked: number;
      completed: number;
      failed: number;
    },
    RuntimeRegistryRunLatest
  >;
  approvals: RuntimeRegistrySection<
    {
      total: number;
      pending: number;
      approved: number;
      rejected: number;
      expired: number;
    },
    RuntimeRegistryApprovalLatest
  >;
  operator: RuntimeRegistrySection<
    {
      runs: number;
      blockedRuns: number;
      completedRuns: number;
      failedRuns: number;
      approvals: number;
      pendingApprovals: number;
      approvedApprovals: number;
      rejectedApprovals: number;
      expiredApprovals: number;
    },
    {
      run?: RuntimeRegistryRunLatest;
      approval?: RuntimeRegistryApprovalLatest;
    }
  >;
  skills: RuntimeRegistrySection<
    {
      builtInSkillCount: number;
      enabledBuiltInSkillCount: number;
      installedSkillCount: number;
      agenticTechniqueCount: number;
      mcpConfiguredServerCount: number;
      mcpEnabledServerCount: number;
      mcpDisabledServerCount: number;
      mcpDisabledToolCount: number;
    },
    RuntimeRegistrySkillLatest
  >;
  mcp: RuntimeRegistrySection<
    {
      serverCount: number;
      configuredServerCount: number;
      enabledServerCount: number;
      disabledServerCount: number;
      reachableServerCount: number;
      degradedServerCount: number;
      blockedServerCount: number;
      toolCount: number;
      resourceCount: number;
      promptCount: number;
    },
    RuntimeRegistryMcpLatest
  >;
  ml: RuntimeRegistrySection<
    {
      total: number;
      local: number;
      cloud: number;
    },
    RuntimeRegistryModelLatest
  >;
  models: RuntimeRegistrySection<
    {
      total: number;
      local: number;
      cloud: number;
    },
    RuntimeRegistryModelLatest
  >;
};

export type RuntimeRegistryHealthSnapshot = {
  status: RuntimeRegistrySectionStatus;
  ready: boolean;
  summary: RuntimeRegistrySnapshot['summary'];
  sections: {
    operator: RuntimeRegistrySnapshot['operator'];
    runs: RuntimeRegistrySnapshot['runs'];
    approvals: RuntimeRegistrySnapshot['approvals'];
    skills: RuntimeRegistrySnapshot['skills'];
    mcp: RuntimeRegistrySnapshot['mcp'];
    ml: RuntimeRegistrySnapshot['ml'];
  };
  latest: {
    run?: RuntimeRegistryRunLatest;
    approval?: RuntimeRegistryApprovalLatest;
    skill?: RuntimeRegistrySkillLatest;
    mcp?: RuntimeRegistryMcpLatest;
    ml?: RuntimeRegistryModelLatest;
  };
};

type RuntimeRegistryInput = {
  models: ModelInfo[];
  capabilities: Pick<
    CapabilityDirectorySnapshot,
    'summary' | 'skills' | 'mcp' | 'mcpStatus' | 'mcpError' | 'discovery'
  >;
  operator: OperatorStatusSnapshot;
  modelError?: string;
};

const approvalRank: CapabilityApprovalLevel[] = ['AUTO', 'CONFIRM', 'SCREEN', 'TWO_FA'];

function pickHighestApproval(levelCounts: Record<CapabilityApprovalLevel, number>): CapabilityApprovalLevel {
  for (let index = approvalRank.length - 1; index >= 0; index -= 1) {
    const level = approvalRank[index];
    if ((levelCounts[level] ?? 0) > 0) {
      return level;
    }
  }

  return 'AUTO';
}

function mapSkillRiskToCapabilityRisk(levelCounts: {
  read_only: number;
  write_safe: number;
  write_sensitive: number;
  destructive: number;
  system_critical: number;
}): CapabilityRiskLevel {
  if ((levelCounts.system_critical ?? 0) > 0 || (levelCounts.destructive ?? 0) > 0) {
    return 'critical';
  }
  if ((levelCounts.write_sensitive ?? 0) > 0) {
    return 'high';
  }
  if ((levelCounts.write_safe ?? 0) > 0) {
    return 'medium';
  }

  return 'low';
}

function statusFromNullable(value: string | undefined, fallback: RuntimeRegistrySectionStatus = 'healthy') {
  if (!value) {
    return fallback;
  }

  const normalized = value.toLowerCase();
  if (normalized === 'healthy' || normalized === 'ready') {
    return 'healthy';
  }
  if (normalized === 'unknown' || normalized === 'skipped') {
    return 'unknown';
  }
  return 'degraded';
}

function createSectionBase(input: {
  status: RuntimeRegistrySectionStatus;
  enabled: boolean;
  source: RuntimeRegistrySectionSource;
  risk: CapabilityRiskLevel;
  approvalRequirement: CapabilityApprovalLevel;
  live: boolean;
  cached: boolean;
  lastError?: string;
}): RuntimeRegistrySectionBase {
  return input;
}

function buildModelLatest(models: ModelInfo[]): RuntimeRegistryModelLatest | undefined {
  const latest = models[0];
  if (!latest) {
    return undefined;
  }

  return {
    id: latest.id,
    title: latest.name,
    provider: latest.provider,
    type: latest.type,
  };
}

export function buildRuntimeRegistrySnapshot(input: RuntimeRegistryInput): RuntimeRegistrySnapshot {
  const capabilities = input.capabilities;
  const models = input.models;
  const operator = input.operator;
  const modelError = input.modelError;

  const operatorStatus = statusFromNullable(operator.status, 'unknown');
  const skillsStatus = statusFromNullable(
    capabilities.discovery.skills.error ? 'degraded' : capabilities.discovery.skills.status
  );
  const mcpStatus = statusFromNullable(capabilities.mcpStatus);
  const modelStatus =
    modelError || models.length === 0 ? 'degraded' : 'healthy';
  const runsStatus =
    operator.runs.total === 0
      ? 'unknown'
      : operator.runs.blocked > 0 || operator.runs.failed > 0
        ? 'degraded'
        : 'healthy';
  const approvalsStatus =
    operator.approvals.total === 0
      ? 'unknown'
      : operator.approvals.expired > 0
        ? 'degraded'
        : 'healthy';

  const skillApprovalRequirement = pickHighestApproval(capabilities.skills.summary.approvalLevelCounts);
  const skillRisk = mapSkillRiskToCapabilityRisk(capabilities.skills.summary.riskLevelCounts);
  const mcpApprovalRequirement = capabilities.summary.mcpConfiguredServerCount > 0 ? 'CONFIRM' : 'AUTO';
  const modelApprovalRequirement: CapabilityApprovalLevel = models.length > 0 ? 'AUTO' : 'CONFIRM';
  const enabledMcpServers = Math.max(0, capabilities.summary.mcpServerCount - capabilities.summary.mcpDisabledServerCount);
  const liveMcpServers = capabilities.summary.mcpReachableServerCount;
  const latestModel = buildModelLatest(models);
  const latestRun = operator.runs.latest
    ? {
        id: operator.runs.latest.id,
        title: operator.runs.latest.title,
        mode: operator.runs.latest.mode,
        status: operator.runs.latest.status,
        updatedAt: operator.runs.latest.updatedAt,
        reasoningDepth: operator.runs.latest.reasoningDepth,
        approvalCount: operator.runs.latest.approvalCount,
        pendingApprovals: operator.runs.latest.pendingApprovals,
      }
    : undefined;
  const latestApproval = operator.approvals.latest
    ? {
        id: operator.approvals.latest.id,
        title: operator.approvals.latest.title,
        status: operator.approvals.latest.status,
        approvalLevel: operator.approvals.latest.approvalLevel,
        riskLevel: operator.approvals.latest.riskLevel,
        requestedAt: operator.approvals.latest.requestedAt,
      }
    : undefined;

  const runs = {
    ...createSectionBase({
      status: runsStatus,
      enabled: true,
      source: 'local',
      risk: operator.runs.blocked > 0 || operator.runs.failed > 0 ? 'high' : 'low',
      approvalRequirement: 'CONFIRM',
      live: true,
      cached: false,
      lastError: undefined,
    }),
    counts: {
      total: operator.runs.total,
      blocked: operator.runs.blocked,
      completed: operator.runs.completed,
      failed: operator.runs.failed,
    },
    latest: latestRun,
  } satisfies RuntimeRegistrySnapshot['runs'];

  const approvals = {
    ...createSectionBase({
      status: approvalsStatus,
      enabled: true,
      source: 'local',
      risk: operator.approvals.expired > 0 ? 'medium' : 'low',
      approvalRequirement: 'CONFIRM',
      live: true,
      cached: false,
      lastError: undefined,
    }),
    counts: {
      total: operator.approvals.total,
      pending: operator.approvals.pending,
      approved: operator.approvals.approved,
      rejected: operator.approvals.rejected,
      expired: operator.approvals.expired,
    },
    latest: latestApproval,
  } satisfies RuntimeRegistrySnapshot['approvals'];

  const ml = {
    ...createSectionBase({
      status: modelStatus,
      enabled: models.length > 0,
      source: models.some((model) => model.type === 'cloud') ? 'mixed' : 'local',
      risk: modelStatus === 'healthy' ? 'low' : 'medium',
      approvalRequirement: modelApprovalRequirement,
      live: models.length > 0 && !modelError,
      cached: false,
      lastError: modelError ?? (models.length > 0 ? undefined : 'no_models_available'),
    }),
    counts: {
      total: models.length,
      local: models.filter((model) => model.type === 'local').length,
      cloud: models.filter((model) => model.type === 'cloud').length,
    },
    latest: latestModel,
  } satisfies RuntimeRegistrySnapshot['ml'];

  const overallStatus:
    | RuntimeRegistrySectionStatus = [operatorStatus, skillsStatus, mcpStatus, modelStatus, runsStatus, approvalsStatus].includes('degraded')
    ? 'degraded'
    : 'healthy';

  return {
    status: overallStatus,
    summary: {
      runCount: operator.runs.total,
      approvalCount: operator.approvals.total,
      pendingApprovalCount: operator.approvals.pending,
      skillCount: capabilities.summary.skillCount,
      enabledSkillCount: capabilities.summary.enabledSkillCount,
      mcpServerCount: capabilities.summary.mcpServerCount,
      mcpEnabledServerCount: enabledMcpServers,
      mcpLiveServerCount: liveMcpServers,
      modelCount: models.length,
      localModelCount: models.filter((model) => model.type === 'local').length,
      cloudModelCount: models.filter((model) => model.type === 'cloud').length,
    },
    runs,
    approvals,
    operator: {
      ...createSectionBase({
        status: operatorStatus,
        enabled: true,
        source: 'local',
        risk: operatorStatus === 'healthy' ? 'medium' : 'high',
        approvalRequirement: 'CONFIRM',
        live: true,
        cached: false,
        lastError: operatorStatus === 'healthy' ? undefined : 'operator_runtime_degraded',
      }),
      counts: {
        runs: operator.runs.total,
        blockedRuns: operator.runs.blocked,
        completedRuns: operator.runs.completed,
        failedRuns: operator.runs.failed,
        approvals: operator.approvals.total,
        pendingApprovals: operator.approvals.pending,
        approvedApprovals: operator.approvals.approved,
        rejectedApprovals: operator.approvals.rejected,
        expiredApprovals: operator.approvals.expired,
      },
      latest: {
        run: latestRun,
        approval: latestApproval,
      },
    },
    skills: {
      ...createSectionBase({
        status: skillsStatus,
        enabled: capabilities.summary.enabledSkillCount > 0,
        source: capabilities.discovery.skills.status === 'ready' ? 'local' : 'cached',
        risk: skillRisk,
        approvalRequirement: skillApprovalRequirement,
        live: capabilities.discovery.skills.status !== 'unavailable',
        cached: capabilities.discovery.skills.status !== 'ready',
        lastError: capabilities.discovery.skills.error ?? capabilities.skills.summary.mcpConfigurationError,
      }),
      counts: {
        builtInSkillCount: capabilities.skills.summary.builtInSkillCount,
        enabledBuiltInSkillCount: capabilities.skills.summary.enabledBuiltInSkillCount,
        installedSkillCount: capabilities.skills.summary.installedSkillCount,
        agenticTechniqueCount: capabilities.skills.summary.agenticTechniqueCount,
        mcpConfiguredServerCount: capabilities.skills.summary.mcpConfiguredServerCount,
        mcpEnabledServerCount: capabilities.skills.summary.mcpEnabledServerCount,
        mcpDisabledServerCount: capabilities.skills.summary.mcpDisabledServerCount,
        mcpDisabledToolCount: capabilities.skills.summary.mcpDisabledToolCount,
      },
      latest: capabilities.skills.builtIn[0]
        ? {
            id: capabilities.skills.builtIn[0].id,
            title: capabilities.skills.builtIn[0].title,
            enabled: capabilities.skills.builtIn[0].enabled,
            approvalLevel: capabilities.skills.builtIn[0].approvalLevel,
            riskLevel: capabilities.skills.builtIn[0].riskLevel,
          }
        : undefined,
    },
    mcp: {
      ...createSectionBase({
        status: mcpStatus,
        enabled: enabledMcpServers > 0,
        source: capabilities.discovery.mcp.cached ? 'cached' : 'local',
        risk: capabilities.summary.mcpBlockedServerCount > 0 ? 'high' : 'medium',
        approvalRequirement: mcpApprovalRequirement,
        live: capabilities.discovery.mcp.status === 'ready' && capabilities.mcpStatus === 'ready',
        cached: Boolean(capabilities.discovery.mcp.cached),
        lastError: capabilities.mcpError ?? capabilities.discovery.mcp.error,
      }),
      counts: {
        serverCount: capabilities.summary.mcpServerCount,
        configuredServerCount: capabilities.summary.mcpConfiguredServerCount,
        enabledServerCount: enabledMcpServers,
        disabledServerCount: capabilities.summary.mcpDisabledServerCount,
        reachableServerCount: capabilities.summary.mcpReachableServerCount,
        degradedServerCount: capabilities.summary.mcpDegradedServerCount,
        blockedServerCount: capabilities.summary.mcpBlockedServerCount,
        toolCount: capabilities.summary.mcpToolCount,
        resourceCount: capabilities.summary.mcpResourceCount,
        promptCount: capabilities.summary.mcpPromptCount,
      },
      latest: capabilities.mcp.mcpServers[0]
        ? {
            id: capabilities.mcp.mcpServers[0].id,
            title: capabilities.mcp.mcpServers[0].id,
            state:
              capabilities.mcp.mcpServers[0].state ?? (capabilities.mcp.mcpServers[0].enabled ? 'configured' : 'disabled'),
            reason: capabilities.mcp.mcpServers[0].stateReason ?? 'No discovery state recorded yet.',
          }
        : undefined,
    },
    ml,
    models: ml,
  };
}

export function buildRuntimeRegistryHealthSnapshot(snapshot: RuntimeRegistrySnapshot): RuntimeRegistryHealthSnapshot {
  return {
    status: snapshot.status,
    ready: snapshot.status === 'healthy',
    summary: snapshot.summary,
    sections: {
      operator: snapshot.operator,
      runs: snapshot.runs,
      approvals: snapshot.approvals,
      skills: snapshot.skills,
      mcp: snapshot.mcp,
      ml: snapshot.ml,
    },
    latest: {
      run: snapshot.runs.latest,
      approval: snapshot.approvals.latest,
      skill: snapshot.skills.latest,
      mcp: snapshot.mcp.latest,
      ml: snapshot.ml.latest,
    },
  };
}
