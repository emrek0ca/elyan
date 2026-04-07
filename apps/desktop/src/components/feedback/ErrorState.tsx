import { AlertTriangle } from "@/vendor/lucide-react";

import { Button } from "@/components/primitives/Button";
import { Surface } from "@/components/primitives/Surface";

type ErrorStateProps = {
  title: string;
  description: string;
  onRetry?: () => void;
};

export function ErrorState({ title, description, onRetry }: ErrorStateProps) {
  return (
    <Surface tone="panel" className="flex min-h-[220px] flex-col items-center justify-center gap-4 p-8 text-center">
      <span className="inline-flex h-12 w-12 items-center justify-center rounded-full bg-[color-mix(in_srgb,var(--state-error)_14%,transparent)] text-[var(--state-error)]">
        <AlertTriangle className="h-5 w-5" />
      </span>
      <div className="space-y-2">
        <h3 className="font-display text-[18px] font-semibold text-[var(--text-primary)]">{title}</h3>
        <p className="mx-auto max-w-md text-[13px] text-[var(--text-secondary)]">{description}</p>
      </div>
      {onRetry ? <Button onClick={onRetry}>Retry</Button> : null}
    </Surface>
  );
}
