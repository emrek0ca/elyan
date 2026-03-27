import type { MetricSummary } from "@/types/domain";
import { Surface } from "@/components/primitives/Surface";
import { StatusBadge } from "@/components/primitives/StatusBadge";

export function MetricTile({ metric }: { metric: MetricSummary }) {
  return (
    <Surface tone="card" className="p-5">
      <div className="mb-4 flex items-center justify-between">
        <span className="text-[11px] uppercase tracking-[0.16em] text-[var(--text-tertiary)]">{metric.label}</span>
        <StatusBadge tone={metric.tone}>{metric.tone}</StatusBadge>
      </div>
      <div className="text-[30px] font-semibold tracking-[-0.04em] text-[var(--text-primary)]">{metric.value}</div>
      <div className="mt-2 text-[12px] text-[var(--text-secondary)]">{metric.meta}</div>
    </Surface>
  );
}

