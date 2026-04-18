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
  MultiAgentMetricsSnapshot,
  OperatorStackSnapshot,
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
  getMultiAgentMetrics,
  getOperatorPreview,
  getOperatorStack,
  getProviderDescriptors,
  getProviders,
  getSecuritySummary,
  getSystemReadiness,
  getWorkspaceInvites,
  getWorkspaceMembers,
  getCreditLedger,
} from "@/services/api/elyan-service";
import { runtimeManager } from "@/runtime/runtime-manager";
import { useUiStore } from "@/stores/ui-store";

function visibleRefetchInterval(ms: number): () => number | false {
  return () => (typeof document === "undefined" || document.visibilityState === "visible" ? ms : false);
}

function useAuthQueryEnabled(): boolean {
  const isAuthenticated = useUiStore((state) => state.isAuthenticated);
  const authHydrated = useUiStore((state) => state.authHydrated);
  return authHydrated && isAuthenticated;
}

export function useHomeSnapshot(): UseQueryResult<HomeSnapshotV2> {
  const authEnabled = useAuthQueryEnabled();
  return useQuery({
    queryKey: ["home-snapshot"],
    queryFn: getHomeSnapshot,
    enabled: authEnabled,
    staleTime: 8000,
    refetchInterval: visibleRefetchInterval(20000),
    refetchOnWindowFocus: false,
  });
}

export function useCoworkHomeSnapshot(): UseQueryResult<CoworkHomeSnapshot> {
  const authEnabled = useAuthQueryEnabled();
  return useQuery({
    queryKey: ["cowork-home"],
    queryFn: getCoworkHome,
    enabled: authEnabled,
    staleTime: 6000,
    refetchInterval: visibleRefetchInterval(15000),
    refetchOnWindowFocus: false,
  });
}

export function useCommandCenterSnapshot(selectedThreadId?: string, selectedRunId?: string): UseQueryResult<CommandCenterSnapshot> {
  const authEnabled = useAuthQueryEnabled();
  return useQuery({
    queryKey: ["command-center", selectedThreadId || "latest-thread", selectedRunId || "latest-run"],
    queryFn: () => getCommandCenterSnapshot(selectedThreadId, selectedRunId),
    enabled: authEnabled,
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
  const authEnabled = useAuthQueryEnabled();
  return useQuery({
    queryKey: ["provider-descriptors"],
    queryFn: getProviderDescriptors,
    enabled: authEnabled,
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

export function useOperatorStack(): UseQueryResult<OperatorStackSnapshot> {
  const authEnabled = useAuthQueryEnabled();
  return useQuery({
    queryKey: ["operator-stack"],
    queryFn: getOperatorStack,
    enabled: authEnabled,
    staleTime: 4000,
    refetchInterval: visibleRefetchInterval(12000),
    refetchOnWindowFocus: false,
  });
}

export function useMultiAgentMetrics(): UseQueryResult<MultiAgentMetricsSnapshot> {
  const authEnabled = useAuthQueryEnabled();
  return useQuery({
    queryKey: ["multi-agent-metrics"],
    queryFn: getMultiAgentMetrics,
    enabled: authEnabled,
    staleTime: 4000,
    refetchInterval: visibleRefetchInterval(10000),
    refetchOnWindowFocus: false,
  });
}

export function useIntegrations(): UseQueryResult<IntegrationSummary[]> {
  const authEnabled = useAuthQueryEnabled();
  return useQuery({
    queryKey: ["integrations"],
    queryFn: getIntegrations,
    enabled: authEnabled,
    staleTime: 60000,
  });
}

export function useConnectors(): UseQueryResult<ConnectorDefinition[]> {
  const authEnabled = useAuthQueryEnabled();
  return useQuery({
    queryKey: ["connectors"],
    queryFn: getConnectors,
    enabled: authEnabled,
    staleTime: 30000,
  });
}

export function useChannels(): UseQueryResult<ChannelSummary[]> {
  const authEnabled = useAuthQueryEnabled();
  return useQuery({
    queryKey: ["channels"],
    queryFn: getChannels,
    enabled: authEnabled,
    staleTime: 8000,
    refetchInterval: visibleRefetchInterval(20000),
    refetchOnWindowFocus: false,
  });
}

export function useChannelsCatalog(): UseQueryResult<ChannelCatalogEntry[]> {
  const authEnabled = useAuthQueryEnabled();
  return useQuery({
    queryKey: ["channels-catalog"],
    queryFn: getChannelsCatalog,
    enabled: authEnabled,
    staleTime: 60000,
  });
}

export function useChannelPairingStatus(channel?: string): UseQueryResult<ChannelPairingStatus> {
  const authEnabled = useAuthQueryEnabled();
  return useQuery({
    queryKey: ["channel-pairing", channel || "none"],
    queryFn: () => getChannelPairingStatus(String(channel || "whatsapp")),
    enabled: authEnabled && Boolean(channel),
    staleTime: 1500,
    refetchInterval: visibleRefetchInterval(5000),
    refetchOnWindowFocus: false,
  });
}

export function useConnectorAccounts(provider?: string): UseQueryResult<ConnectorAccount[]> {
  const authEnabled = useAuthQueryEnabled();
  return useQuery({
    queryKey: ["connector-accounts", provider || "all"],
    queryFn: () => getConnectorAccounts(provider),
    enabled: authEnabled,
    staleTime: 15000,
  });
}

export function useConnectorHealth(): UseQueryResult<ConnectorHealth[]> {
  const authEnabled = useAuthQueryEnabled();
  return useQuery({
    queryKey: ["connector-health"],
    queryFn: getConnectorHealth,
    enabled: authEnabled,
    staleTime: 8000,
    refetchInterval: visibleRefetchInterval(20000),
    refetchOnWindowFocus: false,
  });
}

export function useConnectorTraces(): UseQueryResult<ConnectorActionTrace[]> {
  const authEnabled = useAuthQueryEnabled();
  return useQuery({
    queryKey: ["connector-traces"],
    queryFn: getConnectorTraces,
    enabled: authEnabled,
    staleTime: 10000,
    refetchInterval: visibleRefetchInterval(20000),
    refetchOnWindowFocus: false,
  });
}

export function useLogs(): UseQueryResult<LogEvent[]> {
  const authEnabled = useAuthQueryEnabled();
  return useQuery({
    queryKey: ["logs"],
    queryFn: getLogs,
    enabled: authEnabled,
    staleTime: 12000,
    refetchInterval: visibleRefetchInterval(30000),
    refetchOnWindowFocus: false,
  });
}

export function useSecuritySummary(): UseQueryResult<SecuritySummary> {
  const authEnabled = useAuthQueryEnabled();
  return useQuery({
    queryKey: ["security-summary"],
    queryFn: getSecuritySummary,
    enabled: authEnabled,
    staleTime: 10000,
    refetchInterval: visibleRefetchInterval(20000),
    refetchOnWindowFocus: false,
  });
}

export function useLearningSummary(): UseQueryResult<LearningSummary | null> {
  const authEnabled = useAuthQueryEnabled();
  return useQuery({
    queryKey: ["learning-summary"],
    queryFn: getLearningSummary,
    enabled: authEnabled,
    staleTime: 20000,
    refetchInterval: visibleRefetchInterval(45000),
    refetchOnWindowFocus: false,
  });
}

export function usePrivacySummary(): UseQueryResult<PrivacySummary | null> {
  const authEnabled = useAuthQueryEnabled();
  return useQuery({
    queryKey: ["privacy-summary"],
    queryFn: getPrivacySummary,
    enabled: authEnabled,
    staleTime: 30000,
    refetchInterval: visibleRefetchInterval(60000),
    refetchOnWindowFocus: false,
  });
}

export function useBillingWorkspace(): UseQueryResult<WorkspaceBillingSummary | null> {
  const authEnabled = useAuthQueryEnabled();
  return useQuery({
    queryKey: ["billing-workspace"],
    queryFn: getBillingWorkspace,
    enabled: authEnabled,
    staleTime: 15000,
    refetchInterval: visibleRefetchInterval(30000),
    refetchOnWindowFocus: false,
  });
}

export function useBillingProfile(): UseQueryResult<BillingProfileSummary | null> {
  const authEnabled = useAuthQueryEnabled();
  return useQuery({
    queryKey: ["billing-profile"],
    queryFn: getBillingProfile,
    enabled: authEnabled,
    staleTime: 15000,
    refetchInterval: visibleRefetchInterval(30000),
    refetchOnWindowFocus: false,
  });
}

export function useAdminWorkspaces(): UseQueryResult<WorkspaceAdminSummary[]> {
  const authEnabled = useAuthQueryEnabled();
  return useQuery({
    queryKey: ["admin-workspaces"],
    queryFn: getAdminWorkspaces,
    enabled: authEnabled,
    staleTime: 8000,
    refetchInterval: visibleRefetchInterval(20000),
    refetchOnWindowFocus: false,
  });
}

export function useAdminWorkspaceDetail(workspaceId?: string): UseQueryResult<WorkspaceAdminDetail | null> {
  const authEnabled = useAuthQueryEnabled();
  return useQuery({
    queryKey: ["admin-workspace", workspaceId || "none"],
    queryFn: () => getAdminWorkspaceDetail(String(workspaceId || "")),
    enabled: authEnabled && Boolean(workspaceId),
    staleTime: 6000,
    refetchInterval: visibleRefetchInterval(15000),
    refetchOnWindowFocus: false,
  });
}

export function useWorkspaceMembers(workspaceId?: string): UseQueryResult<WorkspaceMemberSummary[]> {
  const authEnabled = useAuthQueryEnabled();
  return useQuery({
    queryKey: ["workspace-members", workspaceId || "none"],
    queryFn: () => getWorkspaceMembers(String(workspaceId || "")),
    enabled: authEnabled && Boolean(workspaceId),
    staleTime: 6000,
    refetchInterval: visibleRefetchInterval(15000),
    refetchOnWindowFocus: false,
  });
}

export function useWorkspaceInvites(workspaceId?: string): UseQueryResult<WorkspaceInviteSummary[]> {
  const authEnabled = useAuthQueryEnabled();
  return useQuery({
    queryKey: ["workspace-invites", workspaceId || "none"],
    queryFn: () => getWorkspaceInvites(String(workspaceId || "")),
    enabled: authEnabled && Boolean(workspaceId),
    staleTime: 6000,
    refetchInterval: visibleRefetchInterval(15000),
    refetchOnWindowFocus: false,
  });
}

export function useBillingCatalog(): UseQueryResult<{ plans: BillingPlanSummary[]; tokenPacks: TokenPackSummary[] }> {
  const authEnabled = useAuthQueryEnabled();
  return useQuery({
    queryKey: ["billing-catalog"],
    queryFn: getBillingCatalog,
    enabled: authEnabled,
    staleTime: 20000,
    refetchInterval: visibleRefetchInterval(45000),
    refetchOnWindowFocus: false,
  });
}

export function useCreditLedger(limit = 40): UseQueryResult<CreditLedgerEntrySummary[]> {
  const authEnabled = useAuthQueryEnabled();
  return useQuery({
    queryKey: ["credit-ledger", limit],
    queryFn: () => getCreditLedger(limit),
    enabled: authEnabled,
    staleTime: 8000,
    refetchInterval: visibleRefetchInterval(20000),
    refetchOnWindowFocus: false,
  });
}

export function useBillingEvents(limit = 24): UseQueryResult<BillingEventSummary[]> {
  const authEnabled = useAuthQueryEnabled();
  return useQuery({
    queryKey: ["billing-events", limit],
    queryFn: () => getBillingEvents(limit),
    enabled: authEnabled,
    staleTime: 8000,
    refetchInterval: visibleRefetchInterval(20000),
    refetchOnWindowFocus: false,
  });
}

export function useInboxEvents(workspaceId?: string, limit = 8): UseQueryResult<InboxEventSummary[]> {
  const authEnabled = useAuthQueryEnabled();
  return useQuery({
    queryKey: ["inbox-events", workspaceId || "none", limit],
    queryFn: () => getInboxEvents(String(workspaceId || ""), limit),
    enabled: authEnabled && Boolean(workspaceId),
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
