import { Sparkles } from "@/vendor/lucide-react";

import { Button } from "@/components/primitives/Button";
import { Surface } from "@/components/primitives/Surface";

type EmptyStateProps = {
  title: string;
  description: string;
  actionLabel?: string;
  onAction?: () => void;
};

export function EmptyState({ title, description, actionLabel, onAction }: EmptyStateProps) {
  return (
    <Surface tone="panel" className="flex min-h-[220px] flex-col items-center justify-center gap-4 p-8 text-center">
      <span className="inline-flex h-12 w-12 items-center justify-center rounded-full bg-[var(--accent-soft)] text-[var(--accent-primary)]">
        <Sparkles className="h-5 w-5" />
      </span>
      <div className="space-y-2">
        <h3 className="font-display text-[18px] font-semibold text-[var(--text-primary)]">{title}</h3>
        <p className="mx-auto max-w-md text-[13px] text-[var(--text-secondary)]">{description}</p>
      </div>
      {actionLabel && onAction ? <Button onClick={onAction}>{actionLabel}</Button> : null}
    </Surface>
  );
}
