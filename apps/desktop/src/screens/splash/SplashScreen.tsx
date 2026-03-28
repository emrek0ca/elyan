import { AnimatePresence, motion } from "framer-motion";

import { ElyanMark } from "@/components/brand/ElyanMark";

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
            <ElyanMark size="xl" className="h-[180px] w-[180px] rounded-[36px]" alt="Elyan logo" />
            <div className="space-y-2 text-center">
              <div className="font-display text-[34px] font-semibold tracking-[-0.05em] text-[var(--text-primary)]">Elyan</div>
              <div className="text-[13px] text-[var(--text-secondary)]">Secure operator shell</div>
            </div>
            <div className="h-1.5 w-56 overflow-hidden rounded-full bg-[var(--accent-soft)]">
              <motion.div
                className="h-full rounded-full bg-[var(--accent-primary)]"
                initial={{ width: "0%" }}
                animate={{ width: "100%" }}
                transition={{ duration: 1.6, ease: "easeInOut" }}
              />
            </div>
            <div className="text-[12px] text-[var(--text-tertiary)]">Initializing shell</div>
          </div>
        </motion.div>
      ) : null}
    </AnimatePresence>
  );
}
