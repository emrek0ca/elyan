import type { ButtonHTMLAttributes, PropsWithChildren } from "react";

import { cn } from "@/utils/cn";

type ButtonProps = PropsWithChildren<
  ButtonHTMLAttributes<HTMLButtonElement> & {
    variant?: "primary" | "secondary" | "ghost";
    size?: "sm" | "md";
  }
>;

export function Button({
  children,
  className,
  variant = "secondary",
  size = "md",
  ...props
}: ButtonProps) {
  return (
    <button
      className={cn(
        "inline-flex items-center justify-center rounded-[16px] border text-[12px] font-medium tracking-[0.01em] transition-all duration-150 ease-premium focus-visible:focus-ring disabled:cursor-not-allowed disabled:opacity-50",
        size === "md" ? "h-10 px-[18px]" : "h-8 px-[14px] text-[11px]",
        variant === "primary" &&
          "border-transparent bg-[linear-gradient(180deg,color-mix(in_srgb,var(--accent-primary)_94%,white),var(--accent-primary))] text-[var(--accent-contrast)] shadow-[0_14px_30px_var(--accent-glow)] hover:-translate-y-[1px] hover:brightness-[1.02]",
        variant === "secondary" &&
          "border-[var(--border-subtle)] bg-[color-mix(in_srgb,var(--bg-surface)_92%,var(--bg-surface-raised))] text-[var(--text-primary)] shadow-[inset_0_1px_0_rgba(255,255,255,0.45)] hover:-translate-y-[1px] hover:bg-[var(--bg-surface-alt)]",
        variant === "ghost" &&
          "border-transparent bg-transparent text-[var(--text-secondary)] hover:bg-[color-mix(in_srgb,var(--accent-soft)_72%,transparent)] hover:text-[var(--text-primary)]",
        className,
      )}
      {...props}
    >
      {children}
    </button>
  );
}
