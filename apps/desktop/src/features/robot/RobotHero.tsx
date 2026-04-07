import { ElyanMark } from "@/components/brand/ElyanMark";
import { cn } from "@/utils/cn";

type RobotHeroProps = {
  title?: string;
  subtitle?: string;
  compact?: boolean;
};

export function RobotHero({ title, subtitle, compact = false }: RobotHeroProps) {
  return (
    <div className={cn("relative flex flex-col items-center justify-center", compact ? "gap-4 py-6" : "gap-6 py-10")}>
      <div className="absolute inset-x-[20%] bottom-3 h-16 rounded-full bg-[radial-gradient(circle,color-mix(in_srgb,var(--accent-glow)_65%,transparent)_0%,transparent_72%)] blur-3xl" />
      <div className="elyan-float relative">
        <ElyanMark size={compact ? "lg" : "xl"} className={cn("relative z-10", compact ? "h-40 w-40 rounded-[28px]" : "h-56 w-56 rounded-[36px]")} alt="Elyan" />
      </div>
      {title ? (
        <div className="space-y-2 text-center">
          <h1 className={cn("font-display font-semibold tracking-[-0.03em] text-[var(--text-primary)]", compact ? "text-[26px]" : "text-[34px]")}>
            {title}
          </h1>
          {subtitle ? <p className="max-w-2xl text-[14px] text-[var(--text-secondary)]">{subtitle}</p> : null}
        </div>
      ) : null}
    </div>
  );
}
