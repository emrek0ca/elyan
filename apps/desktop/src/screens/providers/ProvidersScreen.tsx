import { KeyRound, TimerReset } from "lucide-react";

import { Button } from "@/components/primitives/Button";
import { SearchField } from "@/components/primitives/SearchField";
import { Surface } from "@/components/primitives/Surface";
import { StatusBadge } from "@/components/primitives/StatusBadge";
import { useProviders } from "@/hooks/use-desktop-data";

export function ProvidersScreen() {
  const { data = [] } = useProviders();

  return (
    <div className="space-y-6">
      <Surface tone="hero" className="px-6 py-6">
        <div className="flex items-end justify-between gap-6">
          <div>
            <div className="text-[11px] uppercase tracking-[0.16em] text-[var(--text-tertiary)]">Provider management</div>
            <h1 className="mt-2 font-display text-[30px] font-semibold tracking-[-0.04em] text-[var(--text-primary)]">
              Multiple model lanes, one controlled surface
            </h1>
            <p className="mt-3 max-w-3xl text-[14px] leading-7 text-[var(--text-secondary)]">
              Keep provider trust, health, latency, and credentials visible without turning the product into an admin panel.
            </p>
          </div>
          <SearchField placeholder="Search provider or model" className="w-[320px]" />
        </div>
      </Surface>

      <div className="grid grid-cols-2 gap-4">
        {data.map((provider) => (
          <Surface key={provider.id} tone="card" className="p-5">
            <div className="mb-4 flex items-start justify-between gap-4">
              <div>
                <div className="text-[16px] font-semibold text-[var(--text-primary)]">{provider.name}</div>
                <div className="mt-1 text-[12px] text-[var(--text-secondary)]">{provider.detail}</div>
              </div>
              <StatusBadge tone={provider.status === "connected" ? "success" : provider.status === "degraded" ? "warning" : "neutral"}>
                {provider.status}
              </StatusBadge>
            </div>
            <div className="grid grid-cols-3 gap-3 text-[12px]">
              <div className="rounded-sm border border-[var(--border-subtle)] bg-[var(--bg-surface-alt)] p-3">
                <div className="text-[var(--text-tertiary)]">Model</div>
                <div className="mt-1 font-medium text-[var(--text-primary)]">{provider.model}</div>
              </div>
              <div className="rounded-sm border border-[var(--border-subtle)] bg-[var(--bg-surface-alt)] p-3">
                <div className="text-[var(--text-tertiary)]">Latency</div>
                <div className="mt-1 font-medium text-[var(--text-primary)]">{provider.latencyMs}ms</div>
              </div>
              <div className="rounded-sm border border-[var(--border-subtle)] bg-[var(--bg-surface-alt)] p-3">
                <div className="text-[var(--text-tertiary)]">Usage</div>
                <div className="mt-1 font-medium text-[var(--text-primary)]">{provider.usageToday.toLocaleString()}</div>
              </div>
            </div>
            <div className="mt-4 rounded-md border border-[var(--border-subtle)] bg-[var(--bg-surface)] p-4">
              <div className="mb-2 flex items-center gap-2 text-[12px] font-medium text-[var(--text-primary)]">
                <KeyRound className="h-4 w-4 text-[var(--accent-primary)]" />
                Secure credentials
              </div>
              <input
                type="password"
                value="••••••••••••••••••••"
                readOnly
                className="h-11 w-full rounded-md border border-[var(--border-subtle)] bg-[var(--bg-surface-alt)] px-4 text-[13px] text-[var(--text-primary)] outline-none"
              />
            </div>
            <div className="mt-4 flex gap-3">
              <Button variant="primary">Connect / Rotate</Button>
              <Button variant="secondary">
                <TimerReset className="mr-2 h-4 w-4" />
                Test health
              </Button>
            </div>
          </Surface>
        ))}
      </div>
    </div>
  );
}

