import { useEffect } from "react";
import { AnimatePresence, motion } from "framer-motion";

import { Button } from "@/components/primitives/Button";

import heroImage from "@assets/image.png";

type WelcomeOverlayProps = {
  open: boolean;
  onClose: () => void;
  reduceMotion?: boolean;
};

export function WelcomeOverlay({ open, onClose, reduceMotion = false }: WelcomeOverlayProps) {
  useEffect(() => {
    if (!open) {
      return;
    }
    const timeout = window.setTimeout(onClose, reduceMotion ? 600 : 1800);
    return () => window.clearTimeout(timeout);
  }, [onClose, open, reduceMotion]);

  return (
    <AnimatePresence>
      {open ? (
        <motion.div
          initial={{ opacity: 0 }}
          animate={{ opacity: 1 }}
          exit={{ opacity: 0 }}
          transition={{ duration: reduceMotion ? 0.16 : 0.28 }}
          className="fixed inset-0 z-50 flex items-center justify-center bg-[color-mix(in_srgb,var(--bg-shell)_84%,white)] backdrop-blur-[10px]"
        >
          <motion.div
            initial={reduceMotion ? { opacity: 1 } : { opacity: 0, y: 24, scale: 0.96 }}
            animate={{ opacity: 1, y: 0, scale: 1 }}
            exit={reduceMotion ? { opacity: 0 } : { opacity: 0, y: -12, scale: 0.98 }}
            transition={{ duration: reduceMotion ? 0.18 : 0.42, ease: [0.22, 1, 0.36, 1] }}
            className="mx-6 w-full max-w-[720px] rounded-[36px] border border-[color-mix(in_srgb,var(--accent-primary)_12%,var(--border-subtle))] bg-[color-mix(in_srgb,var(--bg-surface)_94%,white)] p-8 shadow-[0_30px_80px_rgba(34,62,124,0.10)]"
          >
            <div className="grid items-center gap-8 md:grid-cols-[1.1fr_0.9fr]">
              <div>
                <div className="text-[11px] uppercase tracking-[0.2em] text-[var(--text-tertiary)]">Elyan</div>
                <h1 className="mt-3 font-display text-[40px] font-semibold tracking-[-0.05em] text-[var(--text-primary)]">
                  Calm operator shell
                </h1>
                <p className="mt-4 max-w-[420px] text-[14px] leading-7 text-[var(--text-secondary)]">
                  Tek yüzey, net kontrol, görünür bağlantılar. Elyan görevleri güvenli şekilde çalıştırır ve ne yaptığını açıkça gösterir.
                </p>
                <div className="mt-6 flex items-center gap-3">
                  <Button variant="primary" onClick={onClose}>
                    Başla
                  </Button>
                  <Button variant="ghost" onClick={onClose}>
                    Geç
                  </Button>
                </div>
              </div>
              <motion.div
                animate={reduceMotion ? undefined : { y: [0, -8, 0] }}
                transition={reduceMotion ? undefined : { duration: 4.2, repeat: Number.POSITIVE_INFINITY, ease: "easeInOut" }}
                className="flex items-center justify-center"
              >
                <img
                  src={heroImage}
                  alt="Elyan welcome"
                  className="h-[240px] w-[240px] rounded-[28px] object-cover shadow-[0_18px_48px_rgba(49,74,144,0.14)]"
                />
              </motion.div>
            </div>
          </motion.div>
        </motion.div>
      ) : null}
    </AnimatePresence>
  );
}
