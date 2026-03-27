import { motion } from "framer-motion";

import robotAsset from "@brand/bot_avatar_3d.png";
import { cn } from "@/utils/cn";

type RobotHeroProps = {
  title?: string;
  subtitle?: string;
  compact?: boolean;
};

export function RobotHero({ title, subtitle, compact = false }: RobotHeroProps) {
  return (
    <div className={cn("relative flex flex-col items-center justify-center", compact ? "gap-4 py-6" : "gap-6 py-10")}>
      <div className="absolute inset-x-[18%] bottom-2 h-16 rounded-full bg-[radial-gradient(circle,color-mix(in_srgb,var(--accent-glow)_85%,transparent)_0%,transparent_70%)] blur-3xl" />
      <motion.div
        animate={{ y: [0, -8, 0], scale: [1, 1.012, 1] }}
        transition={{ duration: 6.5, repeat: Number.POSITIVE_INFINITY, ease: "easeInOut" }}
        className="relative"
      >
        <div className="absolute inset-0 rounded-full bg-[radial-gradient(circle,var(--accent-glow)_0%,transparent_65%)] blur-3xl" />
        <div className="absolute inset-[8%] rounded-full border border-[color-mix(in_srgb,var(--accent-primary)_10%,transparent)]" />
        <img
          src={robotAsset}
          alt="Elyan robot"
          className={cn(
            "relative z-10 object-contain drop-shadow-[0_18px_44px_rgba(0,0,0,0.12)]",
            compact ? "h-40 w-40" : "h-56 w-56",
          )}
        />
      </motion.div>
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
