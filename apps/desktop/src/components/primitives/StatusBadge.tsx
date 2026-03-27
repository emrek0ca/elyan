import { cn } from "@/utils/cn";

type StatusBadgeProps = {
  tone: "neutral" | "success" | "warning" | "error" | "info";
  children: string;
};

const toneMap: Record<StatusBadgeProps["tone"], string> = {
  neutral:
    "border-[var(--border-subtle)] bg-[var(--bg-surface)] text-[var(--text-secondary)]",
  success:
    "border-transparent bg-[color-mix(in_srgb,var(--state-success)_12%,transparent)] text-[var(--state-success)]",
  warning:
    "border-transparent bg-[color-mix(in_srgb,var(--state-warning)_16%,transparent)] text-[var(--state-warning)]",
  error:
    "border-transparent bg-[color-mix(in_srgb,var(--state-error)_14%,transparent)] text-[var(--state-error)]",
  info:
    "border-transparent bg-[var(--accent-soft)] text-[var(--accent-primary)]",
};

export function StatusBadge({ tone, children }: StatusBadgeProps) {
  return (
    <span
      className={cn(
        "inline-flex items-center gap-2 rounded-full border px-3 py-1 text-[11px] font-medium tracking-[0.02em]",
        toneMap[tone],
      )}
    >
      <span className="h-1.5 w-1.5 rounded-full bg-current opacity-80" />
      {children}
    </span>
  );
}
