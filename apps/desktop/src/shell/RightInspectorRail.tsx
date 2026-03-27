import { useLocation } from "react-router-dom";
import { Layers3, ShieldCheck, Waypoints } from "lucide-react";

import { Surface } from "@/components/primitives/Surface";
import { StatusBadge } from "@/components/primitives/StatusBadge";
import { useCommandCenterSnapshot, useHomeSnapshot } from "@/hooks/use-desktop-data";
import { useRuntimeStore } from "@/stores/runtime-store";
import { useUiStore } from "@/stores/ui-store";
import { cn } from "@/utils/cn";

export function RightInspectorRail() {
  const collapsed = useUiStore((state) => state.inspectorCollapsed);
  const location = useLocation();
  const home = useHomeSnapshot();
  const command = useCommandCenterSnapshot();
  const connectionState = useRuntimeStore((state) => state.connectionState);
  const sidecarHealth = useRuntimeStore((state) => state.sidecarHealth);

  if (collapsed) {
    return null;
  }

  const isCommand = location.pathname === "/command-center";
  const backends = home.data?.backends ?? [];
  const approvals = command.data?.approvals ?? [];

  return (
    <aside className={cn("hidden w-[336px] shrink-0 border-l border-[var(--border-subtle)] bg-[var(--bg-shell)] p-5 xl:block")}>
      <div className="space-y-5">
        <Surface tone="card" className="p-5">
          <div className="mb-4 flex items-center gap-3">
            <ShieldCheck className="h-4 w-4 text-[var(--accent-primary)]" />
            <div>
              <div className="text-[13px] font-medium text-[var(--text-primary)]">System pulse</div>
              <div className="text-[11px] text-[var(--text-tertiary)]">Quiet health and trust state</div>
            </div>
          </div>
          <div className="space-y-3">
            <div className="rounded-[18px] border border-[var(--border-subtle)] bg-[var(--bg-surface-alt)] p-4">
              <div className="flex items-center justify-between gap-3">
                <div className="text-[12px] font-medium text-[var(--text-primary)]">Managed sidecar</div>
                <StatusBadge
                  tone={
                    connectionState === "connected"
                      ? "success"
                      : connectionState === "booting" || connectionState === "reconnecting"
                        ? "warning"
                        : "error"
                  }
                >
                  {connectionState}
                </StatusBadge>
              </div>
              <div className="mt-2 text-[11px] text-[var(--text-secondary)]">
                {sidecarHealth.runtimeUrl} · port {sidecarHealth.port}
              </div>
            </div>
            {backends.slice(0, 4).map((backend) => (
              <div key={backend.id} className="rounded-[18px] border border-[var(--border-subtle)] bg-[var(--bg-surface-alt)] p-4">
                <div className="flex items-center justify-between gap-3">
                  <div className="text-[12px] font-medium text-[var(--text-primary)]">{backend.label}</div>
                  <StatusBadge tone={backend.active ? "success" : backend.available ? "info" : "warning"}>
                    {backend.active ? "active" : backend.available ? "available" : "fallback"}
                  </StatusBadge>
                </div>
                <div className="mt-2 text-[11px] text-[var(--text-secondary)]">{backend.detail}</div>
              </div>
            ))}
          </div>
        </Surface>

        <Surface tone="card" className="p-5">
          <div className="mb-4 flex items-center gap-3">
            <Waypoints className="h-4 w-4 text-[var(--accent-primary)]" />
            <div>
              <div className="text-[13px] font-medium text-[var(--text-primary)]">
                {isCommand ? "Run context" : "Activity context"}
              </div>
              <div className="text-[11px] text-[var(--text-tertiary)]">Latest operator signals only</div>
            </div>
          </div>
          <div className="space-y-3">
            {(isCommand ? approvals : home.data?.activity ?? []).slice(0, 4).map((item, index) => (
              <div key={"id" in item ? item.id : `approval-${index}`} className="rounded-[18px] border border-[var(--border-subtle)] bg-[var(--bg-surface-alt)] p-4">
                <div className="text-[12px] font-medium text-[var(--text-primary)]">
                  {"action" in item ? item.action : item.title}
                </div>
                <div className="mt-1 text-[11px] text-[var(--text-secondary)]">
                  {"priority" in item ? `${item.priority} approval` : item.detail}
                </div>
              </div>
            ))}
          </div>
        </Surface>

        <Surface tone="card" className="p-5">
          <div className="mb-4 flex items-center gap-3">
            <Layers3 className="h-4 w-4 text-[var(--accent-primary)]" />
            <div>
              <div className="text-[13px] font-medium text-[var(--text-primary)]">Design rules</div>
              <div className="text-[11px] text-[var(--text-tertiary)]">Keep the shell calm and explicit</div>
            </div>
          </div>
          <ul className="space-y-3 text-[12px] text-[var(--text-secondary)]">
            <li>One primary action per screen.</li>
            <li>Risk and approval state never hidden.</li>
            <li>Desktop shell stays keyboard-first and low-noise.</li>
          </ul>
        </Surface>
      </div>
    </aside>
  );
}
