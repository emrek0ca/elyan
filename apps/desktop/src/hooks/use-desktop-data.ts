import { useQuery, type UseQueryResult } from "@tanstack/react-query";

import type {
  CommandCenterSnapshot,
  ChannelCatalogEntry,
  ChannelPairingStatus,
  ChannelSummary,
  ConnectorAccount,
  ConnectorActionTrace,
  ConnectorDefinition,
  ConnectorHealth,
  CoworkHomeSnapshot,
  HomeSnapshotV2,
  IntegrationSummary,
  LogEvent,
  LearningSummary,
  PrivacySummary,
  ProviderDescriptor,
  ProviderSummary,
  SecuritySummary,
  SystemReadiness,
  BillingPlanSummary,
  BillingProfileSummary,
  BillingEventSummary,
  CreditLedgerEntrySummary,
  InboxEventSummary,
  TokenPackSummary,
  WorkspaceInviteSummary,
  WorkspaceBillingSummary,
  WorkspaceAdminDetail,
  WorkspaceAdminSummary,
  WorkspaceMemberSummary,
} from "@/types/domain";
import {
  getAdminWorkspaceDetail,
  getAdminWorkspaces,
  getBillingCatalog,
  getBillingEvents,
  getBillingProfile,
  getBillingWorkspace,
  getChannels,
  getChannelsCatalog,
  getChannelPairingStatus,
  getCommandCenterSnapshot,
  getConnectorAccounts,
  getConnectorHealth,
  getConnectorTraces,
  getConnectors,
  getCoworkHome,
  getInboxEvents,
  getHomeSnapshot,
  getIntegrations,
  getLearningSummary,
  getPrivacySummary,
  getLogs,
  getOperatorPreview,
  getProviderDescriptors,
  getProviders,
  getSecuritySummary,
  getSystemReadiness,
  getWorkspaceInvites,
  getWorkspaceMembers,
  getCreditLedger,
} from "@/services/api/elyan-service";
import { runtimeManager } from "@/runtime/runtime-manager";

function visibleRefetchInterval(ms: number): () => number | false {
  return () => (typeof document === "undefined" || document.visibilityState === "visible" ? ms : false);
}

export function useHomeSnapshot(): UseQueryResult<HomeSnapshotV2> {
  return useQuery({
    queryKey: ["home-snapshot"],
    queryFn: getHomeSnapshot,
    staleTime: 8000,
    refetchInterval: visibleRefetchInterval(20000),
    refetchOnWindowFocus: false,
  });
}

export function useCoworkHomeSnapshot(): UseQueryResult<CoworkHomeSnapshot> {
  return useQuery({
    queryKey: ["cowork-home"],
    queryFn: getCoworkHome,
    staleTime: 6000,
    refetchInterval: visibleRefetchInterval(15000),
    refetchOnWindowFocus: false,
  });
}

export function useCommandCenterSnapshot(selectedThreadId?: string, selectedRunId?: string): UseQueryResult<CommandCenterSnapshot> {
  return useQuery({
    queryKey: ["command-center", selectedThreadId || "latest-thread", selectedRunId || "latest-run"],
    queryFn: () => getCommandCenterSnapshot(selectedThreadId, selectedRunId),
    staleTime: 4000,
    refetchInterval: visibleRefetchInterval(8000),
    refetchOnWindowFocus: false,
  });
}

export function useOperatorPreview(
  text?: string,
  sessionId?: string,
  cacheKey?: string,
): UseQueryResult<CommandCenterSnapshot["orchestration"] | undefined> {
  return useQuery({
    queryKey: ["operator-preview", cacheKey || sessionId || "latest", text || ""],
    queryFn: () => getOperatorPreview(text || "", sessionId, cacheKey),
    enabled: Boolean(String(text || "").trim()),
    staleTime: 5000,
    refetchOnWindowFocus: false,
  });
}

export function useProviders(): UseQueryResult<ProviderSummary[]> {
  return useQuery({
    queryKey: ["providers"],
    queryFn: getProviders,
    staleTime: 60000,
  });
}

export function useProviderDescriptors(): UseQueryResult<ProviderDescriptor[]> {
  return useQuery({
    queryKey: ["provider-descriptors"],
    queryFn: getProviderDescriptors,
    staleTime: 8000,
    refetchInterval: visibleRefetchInterval(20000),
    refetchOnWindowFocus: false,
  });
}

export function useSystemReadiness(): UseQueryResult<SystemReadiness> {
  return useQuery({
    queryKey: ["system-readiness"],
    queryFn: getSystemReadiness,
    staleTime: 2000,
    refetchInterval: visibleRefetchInterval(7000),
    refetchOnWindowFocus: false,
  });
}

export function useIntegrations(): UseQueryResult<IntegrationSummary[]> {
  return useQuery({
    queryKey: ["integrations"],
    queryFn: getIntegrations,
    staleTime: 60000,
  });
}

export function useConnectors(): UseQueryResult<ConnectorDefinition[]> {
  return useQuery({
    queryKey: ["connectors"],
    queryFn: getConnectors,
    staleTime: 30000,
  });
}

export function useChannels(): UseQueryResult<ChannelSummary[]> {
  return useQuery({
    queryKey: ["channels"],
    queryFn: getChannels,
    staleTime: 8000,
    refetchInterval: visibleRefetchInterval(20000),
    refetchOnWindowFocus: false,
  });
}

export function useChannelsCatalog(): UseQueryResult<ChannelCatalogEntry[]> {
  return useQuery({
    queryKey: ["channels-catalog"],
    queryFn: getChannelsCatalog,
    staleTime: 60000,
  });
}

export function useChannelPairingStatus(channel?: string): UseQueryResult<ChannelPairingStatus> {
  return useQuery({
    queryKey: ["channel-pairing", channel || "none"],
    queryFn: () => getChannelPairingStatus(String(channel || "whatsapp")),
    enabled: Boolean(channel),
    staleTime: 1500,
    refetchInterval: visibleRefetchInterval(5000),
    refetchOnWindowFocus: false,
  });
}

export function useConnectorAccounts(provider?: string): UseQueryResult<ConnectorAccount[]> {
  return useQuery({
    queryKey: ["connector-accounts", provider || "all"],
    queryFn: () => getConnectorAccounts(provider),
    staleTime: 15000,
  });
}

export function useConnectorHealth(): UseQueryResult<ConnectorHealth[]> {
  return useQuery({
    queryKey: ["connector-health"],
    queryFn: getConnectorHealth,
    staleTime: 8000,
    refetchInterval: visibleRefetchInterval(20000),
    refetchOnWindowFocus: false,
  });
}

export function useConnectorTraces(): UseQueryResult<ConnectorActionTrace[]> {
  return useQuery({
    queryKey: ["connector-traces"],
    queryFn: getConnectorTraces,
    staleTime: 10000,
    refetchInterval: visibleRefetchInterval(20000),
    refetchOnWindowFocus: false,
  });
}

export function useLogs(): UseQueryResult<LogEvent[]> {
  return useQuery({
    queryKey: ["logs"],
    queryFn: getLogs,
    staleTime: 12000,
    refetchInterval: visibleRefetchInterval(30000),
    refetchOnWindowFocus: false,
  });
}

export function useSecuritySummary(): UseQueryResult<SecuritySummary> {
  return useQuery({
    queryKey: ["security-summary"],
    queryFn: getSecuritySummary,
    staleTime: 10000,
    refetchInterval: visibleRefetchInterval(20000),
    refetchOnWindowFocus: false,
  });
}

export function useLearningSummary(): UseQueryResult<LearningSummary | null> {
  return useQuery({
    queryKey: ["learning-summary"],
    queryFn: getLearningSummary,
    staleTime: 20000,
    refetchInterval: visibleRefetchInterval(45000),
    refetchOnWindowFocus: false,
  });
}

export function usePrivacySummary(): UseQueryResult<PrivacySummary | null> {
  return useQuery({
    queryKey: ["privacy-summary"],
    queryFn: getPrivacySummary,
    staleTime: 30000,
    refetchInterval: visibleRefetchInterval(60000),
    refetchOnWindowFocus: false,
  });
}

export function useBillingWorkspace(): UseQueryResult<WorkspaceBillingSummary | null> {
  return useQuery({
    queryKey: ["billing-workspace"],
    queryFn: getBillingWorkspace,
    staleTime: 15000,
    refetchInterval: visibleRefetchInterval(30000),
    refetchOnWindowFocus: false,
  });
}

export function useBillingProfile(): UseQueryResult<BillingProfileSummary | null> {
  return useQuery({
    queryKey: ["billing-profile"],
    queryFn: getBillingProfile,
    staleTime: 15000,
    refetchInterval: visibleRefetchInterval(30000),
    refetchOnWindowFocus: false,
  });
}

export function useAdminWorkspaces(): UseQueryResult<WorkspaceAdminSummary[]> {
  return useQuery({
    queryKey: ["admin-workspaces"],
    queryFn: getAdminWorkspaces,
    staleTime: 8000,
    refetchInterval: visibleRefetchInterval(20000),
    refetchOnWindowFocus: false,
  });
}

export function useAdminWorkspaceDetail(workspaceId?: string): UseQueryResult<WorkspaceAdminDetail | null> {
  return useQuery({
    queryKey: ["admin-workspace", workspaceId || "none"],
    queryFn: () => getAdminWorkspaceDetail(String(workspaceId || "")),
    enabled: Boolean(workspaceId),
    staleTime: 6000,
    refetchInterval: visibleRefetchInterval(15000),
    refetchOnWindowFocus: false,
  });
}

export function useWorkspaceMembers(workspaceId?: string): UseQueryResult<WorkspaceMemberSummary[]> {
  return useQuery({
    queryKey: ["workspace-members", workspaceId || "none"],
    queryFn: () => getWorkspaceMembers(String(workspaceId || "")),
    enabled: Boolean(workspaceId),
    staleTime: 6000,
    refetchInterval: visibleRefetchInterval(15000),
    refetchOnWindowFocus: false,
  });
}

export function useWorkspaceInvites(workspaceId?: string): UseQueryResult<WorkspaceInviteSummary[]> {
  return useQuery({
    queryKey: ["workspace-invites", workspaceId || "none"],
    queryFn: () => getWorkspaceInvites(String(workspaceId || "")),
    enabled: Boolean(workspaceId),
    staleTime: 6000,
    refetchInterval: visibleRefetchInterval(15000),
    refetchOnWindowFocus: false,
  });
}

export function useBillingCatalog(): UseQueryResult<{ plans: BillingPlanSummary[]; tokenPacks: TokenPackSummary[] }> {
  return useQuery({
    queryKey: ["billing-catalog"],
    queryFn: getBillingCatalog,
    staleTime: 20000,
    refetchInterval: visibleRefetchInterval(45000),
    refetchOnWindowFocus: false,
  });
}

export function useCreditLedger(limit = 40): UseQueryResult<CreditLedgerEntrySummary[]> {
  return useQuery({
    queryKey: ["credit-ledger", limit],
    queryFn: () => getCreditLedger(limit),
    staleTime: 8000,
    refetchInterval: visibleRefetchInterval(20000),
    refetchOnWindowFocus: false,
  });
}

export function useBillingEvents(limit = 24): UseQueryResult<BillingEventSummary[]> {
  return useQuery({
    queryKey: ["billing-events", limit],
    queryFn: () => getBillingEvents(limit),
    staleTime: 8000,
    refetchInterval: visibleRefetchInterval(20000),
    refetchOnWindowFocus: false,
  });
}

export function useInboxEvents(workspaceId?: string, limit = 8): UseQueryResult<InboxEventSummary[]> {
  return useQuery({
    queryKey: ["inbox-events", workspaceId || "none", limit],
    queryFn: () => getInboxEvents(String(workspaceId || ""), limit),
    enabled: Boolean(workspaceId),
    staleTime: 5000,
    refetchInterval: visibleRefetchInterval(12000),
    refetchOnWindowFocus: false,
  });
}

export function useSidecarLogs(): UseQueryResult<string[]> {
  return useQuery({
    queryKey: ["sidecar-logs"],
    queryFn: () => runtimeManager.getRuntimeLogs(),
    staleTime: 2000,
    refetchInterval: visibleRefetchInterval(8000),
    refetchOnWindowFocus: false,
  });
}
