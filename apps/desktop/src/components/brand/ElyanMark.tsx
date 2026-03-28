import brandImage from "@assets/image.png";
import { cn } from "@/utils/cn";

type ElyanMarkProps = {
  size?: "sm" | "md" | "lg" | "xl";
  className?: string;
  alt?: string;
};

const sizeClasses = {
  sm: "h-10 w-10 rounded-[14px]",
  md: "h-14 w-14 rounded-[18px]",
  lg: "h-24 w-24 rounded-[24px]",
  xl: "h-40 w-40 rounded-[32px]",
};

export function ElyanMark({ size = "md", className, alt = "Elyan" }: ElyanMarkProps) {
  return (
    <div
      className={cn(
        "relative overflow-hidden border border-[color-mix(in_srgb,var(--accent-primary)_14%,var(--border-subtle))] bg-[linear-gradient(180deg,color-mix(in_srgb,var(--accent-soft)_76%,white),var(--bg-surface))] shadow-[0_18px_40px_rgba(43,72,145,0.12)]",
        sizeClasses[size],
        className,
      )}
    >
      <img src={brandImage} alt={alt} className="h-full w-full object-contain p-[10%]" />
    </div>
  );
}
