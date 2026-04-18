import type { PropsWithChildren } from "react";
import { useEffect, useState } from "react";
import { QueryClient, QueryClientProvider, useQueryClient } from "@tanstack/react-query";

import { runtimeManager } from "@/runtime/runtime-manager";
import { useRuntimeStore } from "@/stores/runtime-store";
import { useUiStore } from "@/stores/ui-store";
import { runtimeSocketBridge } from "@/services/websocket/runtime-socket";
import { apiClient } from "@/services/api/client";
import { getCurrentLocalUser, getSystemReadiness } from "@/services/api/elyan-service";

function RuntimeBridge() {
  const queryClient = useQueryClient();
  const setSidecarHealth = useRuntimeStore((state) => state.setSidecarHealth);
  const setAuthHydrated = useUiStore((state) => state.setAuthHydrated);

  useEffect(() => {
    let disposed = false;
    let socketIdentity = "";
    let disconnectSocket: () => void = () => undefined;

    const invalidateRuntimeQueries = () => {
      queryClient.invalidateQueries({ queryKey: ["cowork-home"] }).catch(() => undefined);
      queryClient.invalidateQueries({ queryKey: ["home-snapshot"] }).catch(() => undefined);
      queryClient.invalidateQueries({ queryKey: ["command-center"] }).catch(() => undefined);
      queryClient.invalidateQueries({ queryKey: ["connectors"] }).catch(() => undefined);
      queryClient.invalidateQueries({ queryKey: ["connector-accounts"] }).catch(() => undefined);
      queryClient.invalidateQueries({ queryKey: ["connector-health"] }).catch(() => undefined);
      queryClient.invalidateQueries({ queryKey: ["connector-traces"] }).catch(() => undefined);
      queryClient.invalidateQueries({ queryKey: ["billing-workspace"] }).catch(() => undefined);
      queryClient.invalidateQueries({ queryKey: ["admin-workspaces"] }).catch(() => undefined);
      queryClient.invalidateQueries({ queryKey: ["admin-workspace"] }).catch(() => undefined);
      queryClient.invalidateQueries({ queryKey: ["workspace-members"] }).catch(() => undefined);
      queryClient.invalidateQueries({ queryKey: ["workspace-invites"] }).catch(() => undefined);
      queryClient.invalidateQueries({ queryKey: ["inbox-events"] }).catch(() => undefined);
      queryClient.invalidateQueries({ queryKey: ["learning-summary"] }).catch(() => undefined);
      queryClient.invalidateQueries({ queryKey: ["privacy-summary"] }).catch(() => undefined);
      queryClient.invalidateQueries({ queryKey: ["logs"] }).catch(() => undefined);
      queryClient.invalidateQueries({ queryKey: ["security-summary"] }).catch(() => undefined);
      queryClient.invalidateQueries({ queryKey: ["sidecar-logs"] }).catch(() => undefined);
      queryClient.invalidateQueries({ queryKey: ["provider-descriptors"] }).catch(() => undefined);
      queryClient.invalidateQueries({ queryKey: ["system-readiness"] }).catch(() => undefined);
      queryClient.invalidateQueries({ queryKey: ["billing-catalog"] }).catch(() => undefined);
      queryClient.invalidateQueries({ queryKey: ["credit-ledger"] }).catch(() => undefined);
    };

    const handleRuntimeEvent = (event: { type: string; payload: unknown }) => {
      const payload = (event.payload || {}) as Record<string, unknown>;
      const selectedThreadId = useUiStore.getState().selectedThreadId;
      const selectedRunId = useUiStore.getState().selectedRunId;

      if (event.type.startsWith("cowork.")) {
        queryClient.invalidateQueries({ queryKey: ["cowork-home"] }).catch(() => undefined);
        queryClient.invalidateQueries({ queryKey: ["home-snapshot"] }).catch(() => undefined);
        queryClient.invalidateQueries({ queryKey: ["logs"] }).catch(() => undefined);
        const payloadThreadId = String(payload.thread_id || payload.threadId || "");
        if (selectedThreadId && payloadThreadId === selectedThreadId) {
          queryClient.setQueryData(["command-center", selectedThreadId, selectedRunId || "latest-run"], (current: unknown) => {
            if (!current || typeof current !== "object") {
              return current;
            }
            const snapshot = current as Record<string, unknown>;
            const selectedThread = snapshot.selectedThread && typeof snapshot.selectedThread === "object"
              ? { ...(snapshot.selectedThread as Record<string, unknown>) }
              : null;
            if (selectedThread) {
              selectedThread.status = String(payload.status || selectedThread.status || "");
            }
            return {
              ...snapshot,
              selectedThread,
            };
          });
          queryClient.invalidateQueries({ queryKey: ["command-center", selectedThreadId, selectedRunId || "latest-run"] }).catch(() => undefined);
        } else {
          queryClient.invalidateQueries({ queryKey: ["command-center"] }).catch(() => undefined);
        }
        return;
      }

      if (event.type.includes("integration") || event.type.includes("connector")) {
        queryClient.invalidateQueries({ queryKey: ["connectors"] }).catch(() => undefined);
        queryClient.invalidateQueries({ queryKey: ["connector-accounts"] }).catch(() => undefined);
        queryClient.invalidateQueries({ queryKey: ["connector-health"] }).catch(() => undefined);
        queryClient.invalidateQueries({ queryKey: ["connector-traces"] }).catch(() => undefined);
        return;
      }

      invalidateRuntimeQueries();
    };

    const syncSocket = (baseUrl: string, token: string, isHealthy: boolean) => {
      const normalizedToken = token.trim();
      const identity = `${baseUrl}::${normalizedToken}`;
      if (!isHealthy || !normalizedToken) {
        if (socketIdentity) {
          disconnectSocket();
          socketIdentity = "";
        }
        return;
      }
      if (socketIdentity === identity && runtimeSocketBridge.isConnected()) {
        return;
      }
      disconnectSocket();
      socketIdentity = identity;
      disconnectSocket = runtimeSocketBridge.connect(baseUrl, normalizedToken, handleRuntimeEvent);
    };

    const syncHealth = async (boot = false) => {
      const health = boot
        ? await runtimeManager.bootRuntime()
        : await runtimeManager.getRuntimeHealth();
      if (disposed) {
        return;
      }
      apiClient.setBaseUrl(health.runtimeUrl);
      apiClient.setAdminToken(health.adminToken || "");
      setSidecarHealth(health);
      syncSocket(health.runtimeUrl, health.adminToken || apiClient.getSessionToken(), health.status === "healthy");
      if (health.status === "healthy") {
        invalidateRuntimeQueries();
      }
    };

    const hydrateAuth = async () => {
      try {
        const currentUser = await getCurrentLocalUser();
        if (disposed) {
          return;
        }
        if (!currentUser) {
          useUiStore.getState().signOut();
          return;
        }
        useUiStore.getState().signIn(currentUser.email);
      } catch (error) {
        if (!disposed) {
          console.warn("auth hydration skipped after transient failure", error);
        }
      } finally {
        if (!disposed) {
          setAuthHydrated(true);
        }
      }
    };

    const hydrateSetup = async () => {
      const readiness = await getSystemReadiness().catch(() => null);
      if (disposed || !readiness) {
        return;
      }
      useUiStore.getState().setOnboardingComplete(Boolean(readiness.setupComplete));
    };

    void (async () => {
      await syncHealth(true);
      await hydrateAuth();
      await hydrateSetup();
      await syncHealth(false);
    })();
    const interval = window.setInterval(() => {
      void syncHealth(false);
    }, 5000);

    return () => {
      disposed = true;
      window.clearInterval(interval);
      disconnectSocket();
    };
  }, [queryClient, setAuthHydrated, setSidecarHealth]);

  return null;
}

export function AppProviders({ children }: PropsWithChildren) {
  const [queryClient] = useState(
    () =>
      new QueryClient({
        defaultOptions: {
          queries: {
            refetchOnWindowFocus: false,
            retry: 1,
          },
        },
      }),
  );

  return (
    <QueryClientProvider client={queryClient}>
      <RuntimeBridge />
      {children}
    </QueryClientProvider>
  );
}
