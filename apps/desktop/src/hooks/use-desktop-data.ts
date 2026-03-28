import { useQuery, type UseQueryResult } from "@tanstack/react-query";

import type {
  CommandCenterSnapshot,
  ChannelCatalogEntry,
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
  ProviderSummary,
  SecuritySummary,
  WorkspaceBillingSummary,
} from "@/types/domain";
import {
  getBillingWorkspace,
  getChannels,
  getChannelsCatalog,
  getCommandCenterSnapshot,
  getConnectorAccounts,
  getConnectorHealth,
  getConnectorTraces,
  getConnectors,
  getCoworkHome,
  getHomeSnapshot,
  getIntegrations,
  getLearningSummary,
  getLogs,
  getProviders,
  getSecuritySummary,
} from "@/services/api/elyan-service";
import { runtimeManager } from "@/runtime/runtime-manager";

export function useHomeSnapshot(): UseQueryResult<HomeSnapshotV2> {
  return useQuery({
    queryKey: ["home-snapshot"],
    queryFn: getHomeSnapshot,
    refetchInterval: 15000,
  });
}

export function useCoworkHomeSnapshot(): UseQueryResult<CoworkHomeSnapshot> {
  return useQuery({
    queryKey: ["cowork-home"],
    queryFn: getCoworkHome,
    refetchInterval: 12000,
  });
}

export function useCommandCenterSnapshot(selectedThreadId?: string, selectedRunId?: string): UseQueryResult<CommandCenterSnapshot> {
  return useQuery({
    queryKey: ["command-center", selectedThreadId || "latest-thread", selectedRunId || "latest-run"],
    queryFn: () => getCommandCenterSnapshot(selectedThreadId, selectedRunId),
    refetchInterval: 10000,
  });
}

export function useProviders(): UseQueryResult<ProviderSummary[]> {
  return useQuery({
    queryKey: ["providers"],
    queryFn: getProviders,
    staleTime: 60000,
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
    refetchInterval: 15000,
  });
}

export function useChannelsCatalog(): UseQueryResult<ChannelCatalogEntry[]> {
  return useQuery({
    queryKey: ["channels-catalog"],
    queryFn: getChannelsCatalog,
    staleTime: 60000,
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
    refetchInterval: 15000,
  });
}

export function useConnectorTraces(): UseQueryResult<ConnectorActionTrace[]> {
  return useQuery({
    queryKey: ["connector-traces"],
    queryFn: getConnectorTraces,
    refetchInterval: 15000,
  });
}

export function useLogs(): UseQueryResult<LogEvent[]> {
  return useQuery({
    queryKey: ["logs"],
    queryFn: getLogs,
    refetchInterval: 20000,
  });
}

export function useSecuritySummary(): UseQueryResult<SecuritySummary> {
  return useQuery({
    queryKey: ["security-summary"],
    queryFn: getSecuritySummary,
    refetchInterval: 15000,
  });
}

export function useLearningSummary(): UseQueryResult<LearningSummary | null> {
  return useQuery({
    queryKey: ["learning-summary"],
    queryFn: getLearningSummary,
    refetchInterval: 30000,
  });
}

export function useBillingWorkspace(): UseQueryResult<WorkspaceBillingSummary | null> {
  return useQuery({
    queryKey: ["billing-workspace"],
    queryFn: getBillingWorkspace,
    refetchInterval: 20000,
  });
}

export function useSidecarLogs(): UseQueryResult<string[]> {
  return useQuery({
    queryKey: ["sidecar-logs"],
    queryFn: () => runtimeManager.getRuntimeLogs(),
    refetchInterval: 5000,
  });
}
