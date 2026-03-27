import { AnimatePresence, motion } from "framer-motion";

import { RobotHero } from "@/features/robot/RobotHero";

export function SplashScreen({ visible }: { visible: boolean }) {
  return (
    <AnimatePresence>
      {visible ? (
        <motion.div
          className="fixed inset-0 z-[100] flex items-center justify-center bg-[var(--bg-shell)]"
          initial={{ opacity: 1 }}
          exit={{ opacity: 0, transition: { duration: 0.32 } }}
        >
          <div className="flex max-w-2xl flex-col items-center gap-8 px-6">
            <RobotHero
              compact
              title="Elyan"
              subtitle="Policy-driven, cross-device agent operating layer for secure task execution"
            />
            <div className="h-1.5 w-56 overflow-hidden rounded-full bg-[var(--accent-soft)]">
              <motion.div
                className="h-full rounded-full bg-[var(--accent-primary)]"
                initial={{ width: "0%" }}
                animate={{ width: "100%" }}
                transition={{ duration: 1.6, ease: "easeInOut" }}
              />
            </div>
            <div className="text-[12px] text-[var(--text-tertiary)]">Initializing shell, runtime bridge, and command surfaces</div>
          </div>
        </motion.div>
      ) : null}
    </AnimatePresence>
  );
}
