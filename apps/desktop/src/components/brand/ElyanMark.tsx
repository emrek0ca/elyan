import brandImage from "@assets/image.png";
import { cn } from "@/utils/cn";

type ElyanMarkProps = {
  size?: "sm" | "md" | "lg" | "xl";
  className?: string;
  alt?: string;
};

const sizeClasses = {
  sm: "h-10 w-10",
  md: "h-14 w-14",
  lg: "h-24 w-24",
  xl: "h-40 w-40",
};

export function ElyanMark({ size = "md", className, alt = "Elyan" }: ElyanMarkProps) {
  return (
    <img
      src={brandImage}
      alt={alt}
      className={cn("select-none object-contain drop-shadow-[0_14px_26px_rgba(43,72,145,0.12)]", sizeClasses[size], className)}
    />
  );
}
