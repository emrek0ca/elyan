import { useMemo, useState } from "react";

import { Button } from "@/components/primitives/Button";
import { SearchField } from "@/components/primitives/SearchField";
import { Surface } from "@/components/primitives/Surface";
import { StatusBadge } from "@/components/primitives/StatusBadge";
import { useLogs, useSidecarLogs } from "@/hooks/use-desktop-data";
import { runtimeManager } from "@/runtime/runtime-manager";
import { useRuntimeStore } from "@/stores/runtime-store";

export function LogsScreen() {
  const { data = [] } = useLogs();
  const { data: sidecarLogs = [] } = useSidecarLogs();
  const [query, setQuery] = useState("");
  const [scope, setScope] = useState<"all" | "security" | "runtime">("all");
  const [exportBusy, setExportBusy] = useState(false);
  const connectionState = useRuntimeStore((state) => state.connectionState);
  const sidecarHealth = useRuntimeStore((state) => state.sidecarHealth);

  const filtered = useMemo(() => {
    const normalized = data.filter((item) => {
      if (scope === "security") {
        return item.category === "security" || item.source === "security";
      }
      if (scope === "runtime") {
        return item.category !== "security" && item.source !== "security";
      }
      return true;
    });
    if (!query.trim()) {
      return normalized;
    }
    return normalized.filter((item) =>
      `${item.title} ${item.detail} ${item.source}`.toLowerCase().includes(query.toLowerCase()),
    );
  }, [data, query, scope]);

  async function handleExportLogs() {
    setExportBusy(true);
    try {
      const exported = await runtimeManager.exportRuntimeLogs();
      if (exported) {
        await runtimeManager.revealInFolder(exported);
      }
    } finally {
      setExportBusy(false);
    }
  }

  return (
    <div className="space-y-6">
      <Surface tone="hero" className="px-6 py-6">
        <div className="flex flex-wrap items-center justify-between gap-4">
          <div>
            <div className="text-[11px] uppercase tracking-[0.16em] text-[var(--text-tertiary)]">Logs</div>
            <h1 className="mt-2 font-display text-[28px] font-semibold tracking-[-0.04em] text-[var(--text-primary)]">
              Activity feed
            </h1>
          </div>
          <SearchField value={query} onChange={(event) => setQuery(event.target.value)} placeholder="Search logs" className="w-[260px]" />
        </div>
        <div className="mt-3 flex flex-wrap gap-2">
          {(["all", "security", "runtime"] as const).map((item) => (
            <button
              key={item}
              type="button"
              onClick={() => setScope(item)}
              className={`rounded-full border px-3 py-2 text-[12px] font-medium transition ${
                scope === item
                  ? "border-[color-mix(in_srgb,var(--accent-primary)_35%,transparent)] bg-[var(--accent-soft)] text-[var(--accent-primary)]"
                  : "border-[var(--border-subtle)] bg-[var(--bg-surface)] text-[var(--text-secondary)] hover:text-[var(--text-primary)]"
              }`}
            >
              {item}
            </button>
          ))}
        </div>
      </Surface>

      <Surface tone="card" className="p-5">
        <div className="space-y-3">
          {filtered.length ? (
            filtered.map((item) => (
              <div
                key={item.id}
                className={`rounded-md border p-4 ${
                  item.category === "security" || item.source === "security"
                    ? "border-[color-mix(in_srgb,var(--accent-primary)_22%,var(--border-subtle))] bg-[color-mix(in_srgb,var(--accent-soft)_60%,var(--bg-surface-alt))]"
                    : "border-[var(--border-subtle)] bg-[var(--bg-surface-alt)]"
                }`}
              >
                <div className="flex items-start justify-between gap-4">
                  <div className="space-y-1">
                    <div className="text-[13px] font-medium text-[var(--text-primary)]">{item.title}</div>
                    <div className="font-mono text-[12px] leading-6 text-[var(--text-secondary)]">{item.detail}</div>
                  </div>
                  <StatusBadge tone={item.level === "error" ? "error" : item.level === "warning" ? "warning" : item.level === "success" ? "success" : "info"}>
                    {item.timestamp}
                  </StatusBadge>
                </div>
                <div className="mt-3 text-[11px] uppercase tracking-[0.12em] text-[var(--text-tertiary)]">{item.source}</div>
              </div>
            ))
          ) : (
            <div className="rounded-md border border-[var(--border-subtle)] bg-[var(--bg-surface-alt)] p-4 text-[13px] text-[var(--text-secondary)]">
              No log events match the current filter.
            </div>
          )}
        </div>
      </Surface>

      <Surface tone="card" className="p-5">
        <div className="mb-4 flex items-center justify-between gap-4">
          <div>
            <div className="text-[11px] uppercase tracking-[0.16em] text-[var(--text-tertiary)]">Sidecar</div>
            <div className="mt-2 text-[13px] font-medium text-[var(--text-primary)]">Local runtime</div>
            <div className="mt-2 text-[12px] leading-6 text-[var(--text-secondary)]">
              {sidecarHealth.runtimeVersion ? `Runtime ${sidecarHealth.runtimeVersion}` : "Runtime version not reported yet"}
              {sidecarHealth.runtimeProtocolVersion ? ` · protocol ${sidecarHealth.runtimeProtocolVersion}` : ""}
            </div>
          </div>
          <div className="flex items-center gap-2">
            <Button variant="ghost" size="sm" onClick={() => void handleExportLogs()} disabled={exportBusy}>
              {exportBusy ? "Exporting…" : "Export logs"}
            </Button>
            <StatusBadge
              tone={
                sidecarHealth.compatible === false
                  ? "warning"
                  : connectionState === "connected"
                    ? "success"
                    : connectionState === "booting" || connectionState === "reconnecting"
                      ? "warning"
                      : "error"
              }
            >
              {sidecarHealth.compatible === false ? "protocol mismatch" : sidecarHealth.managed ? "managed" : "external"}
            </StatusBadge>
          </div>
        </div>
        <div className="rounded-md border border-[var(--border-subtle)] bg-[var(--bg-surface-alt)] p-4 font-mono text-[12px] leading-6 text-[var(--text-secondary)]">
          {sidecarLogs.length ? (
            <div className="space-y-1">
              {sidecarLogs.slice(-12).map((line, index) => (
                <div key={`${index}-${line.slice(0, 24)}`}>{line}</div>
              ))}
            </div>
          ) : (
            <div>No managed sidecar output captured yet.</div>
          )}
        </div>
        {sidecarHealth.lastLogsExportPath ? (
          <div className="mt-3 text-[11px] uppercase tracking-[0.12em] text-[var(--text-tertiary)]">
            Last export: {sidecarHealth.lastLogsExportPath}
          </div>
        ) : null}
      </Surface>
    </div>
  );
}
