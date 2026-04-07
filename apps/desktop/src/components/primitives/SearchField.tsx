import type { InputHTMLAttributes } from "react";

import { Search } from "@/vendor/lucide-react";

import { cn } from "@/utils/cn";

export function SearchField({ className, ...props }: InputHTMLAttributes<HTMLInputElement>) {
  return (
    <label
      className={cn(
        "flex h-11 items-center gap-3 rounded-[18px] border border-[var(--border-subtle)] bg-[color-mix(in_srgb,var(--bg-surface)_94%,var(--bg-surface-raised))] px-4 text-[var(--text-secondary)] shadow-[inset_0_1px_0_rgba(255,255,255,0.46),var(--shadow-panel)] transition-all duration-150 ease-premium focus-within:focus-ring",
        className,
      )}
    >
      <Search className="h-4 w-4 text-[var(--accent-primary)]" />
      <input
        className="w-full bg-transparent text-[14px] text-[var(--text-primary)] outline-none placeholder:text-[var(--text-tertiary)]"
        {...props}
      />
    </label>
  );
}
