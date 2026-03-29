import type { PropsWithChildren } from "react";
import { useEffect, useState } from "react";
import { QueryClient, QueryClientProvider, useQueryClient } from "@tanstack/react-query";

import { runtimeManager } from "@/runtime/runtime-manager";
import { useRuntimeStore } from "@/stores/runtime-store";
import { useUiStore } from "@/stores/ui-store";
import { runtimeSocketBridge } from "@/services/websocket/runtime-socket";
import { apiClient } from "@/services/api/client";
import { getCurrentLocalUser } from "@/services/api/elyan-service";

function RuntimeBridge() {
  const queryClient = useQueryClient();
  const setSidecarHealth = useRuntimeStore((state) => state.setSidecarHealth);

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
      queryClient.invalidateQueries({ queryKey: ["logs"] }).catch(() => undefined);
      queryClient.invalidateQueries({ queryKey: ["security-summary"] }).catch(() => undefined);
      queryClient.invalidateQueries({ queryKey: ["sidecar-logs"] }).catch(() => undefined);
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
      if (socketIdentity === identity) {
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
      setSidecarHealth(health);
      syncSocket(health.runtimeUrl, health.adminToken || apiClient.getSessionToken(), health.status === "healthy");
      if (health.status === "healthy") {
        invalidateRuntimeQueries();
      }
    };

    const hydrateAuth = async () => {
      const currentUser = await getCurrentLocalUser().catch(() => null);
      if (disposed || !currentUser) {
        return;
      }
      useUiStore.getState().signIn(currentUser.email);
    };

    void (async () => {
      await syncHealth(true);
      await hydrateAuth();
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
  }, [queryClient, setSidecarHealth]);

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
