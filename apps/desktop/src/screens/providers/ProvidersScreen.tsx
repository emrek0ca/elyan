import { Surface } from "@/components/primitives/Surface";
import { StatusBadge } from "@/components/primitives/StatusBadge";
import { useProviders } from "@/hooks/use-desktop-data";

export function ProvidersScreen() {
  const { data = [] } = useProviders();

  return (
    <div className="space-y-6">
      <Surface tone="hero" className="px-6 py-6">
        <div className="max-w-[720px]">
          <div className="text-[11px] uppercase tracking-[0.16em] text-[var(--text-tertiary)]">Models</div>
          <h1 className="mt-2 font-display text-[28px] font-semibold tracking-[-0.04em] text-[var(--text-primary)]">
            Providers
          </h1>
        </div>
      </Surface>

      <div className="grid gap-4 md:grid-cols-2">
        {!data.length ? (
          <Surface tone="card" className="p-5">
            <div className="text-[13px] text-[var(--text-secondary)]">No provider data yet.</div>
          </Surface>
        ) : null}
        {data.map((provider) => (
          <Surface key={provider.id} tone="card" className="p-5">
            <div className="flex items-start justify-between gap-4">
              <div>
                <div className="text-[16px] font-semibold text-[var(--text-primary)]">{provider.name}</div>
                {provider.detail ? <div className="mt-1 text-[12px] text-[var(--text-secondary)]">{provider.detail}</div> : null}
              </div>
              <StatusBadge tone={provider.status === "connected" ? "success" : provider.status === "degraded" ? "warning" : "neutral"}>
                {provider.status}
              </StatusBadge>
            </div>
            <div className="mt-4 grid grid-cols-2 gap-3">
              <div className="rounded-[16px] border border-[var(--border-subtle)] bg-[var(--bg-surface-alt)] p-4">
                <div className="text-[11px] uppercase tracking-[0.12em] text-[var(--text-tertiary)]">Model</div>
                <div className="mt-2 text-[14px] font-medium text-[var(--text-primary)]">{provider.model}</div>
              </div>
              <div className="rounded-[16px] border border-[var(--border-subtle)] bg-[var(--bg-surface-alt)] p-4">
                <div className="text-[11px] uppercase tracking-[0.12em] text-[var(--text-tertiary)]">Latency</div>
                <div className="mt-2 text-[14px] font-medium text-[var(--text-primary)]">{provider.latencyMs}ms</div>
              </div>
            </div>
          </Surface>
        ))}
      </div>
    </div>
  );
}
