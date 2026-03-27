import type { HTMLAttributes, PropsWithChildren } from "react";

import { cn } from "@/utils/cn";

type SurfaceProps = PropsWithChildren<
  HTMLAttributes<HTMLDivElement> & {
    tone?: "card" | "panel" | "hero";
  }
>;

export function Surface({ children, className, tone = "card", ...props }: SurfaceProps) {
  return (
    <div
      className={cn(
        tone === "card" && "surface-card",
        tone === "panel" && "surface-panel",
        tone === "hero" && "surface-hero",
        className,
      )}
      {...props}
    >
      {children}
    </div>
  );
}

