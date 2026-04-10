import { useEffect } from "react";

import { Button } from "@/components/primitives/Button";

import heroImage from "../../../src-tauri/icons/icon.png";

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

  if (!open) {
    return null;
  }

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-[color-mix(in_srgb,var(--bg-shell)_84%,white)] backdrop-blur-[10px]">
      <div className="mx-6 w-full max-w-[720px] rounded-[36px] border border-[color-mix(in_srgb,var(--accent-primary)_12%,var(--border-subtle))] bg-[color-mix(in_srgb,var(--bg-surface)_94%,white)] p-8 shadow-[0_30px_80px_rgba(34,62,124,0.10)]">
        <div className="grid items-center gap-8 md:grid-cols-[1.1fr_0.9fr]">
          <div>
            <div className="text-[11px] uppercase tracking-[0.2em] text-[var(--text-tertiary)]">Elyan</div>
            <h1 className="mt-3 font-display text-[40px] font-semibold tracking-[-0.05em] text-[var(--text-primary)]">
              Calm operator shell
            </h1>
            <p className="mt-4 max-w-[420px] text-[14px] leading-7 text-[var(--text-secondary)]">
              Tek yuzey, net kontrol, gorunur baglantilar. Elyan gorevleri guvenli sekilde calistirir ve ne yaptigini acikca gosterir.
            </p>
            <div className="mt-6 flex items-center gap-3">
              <Button variant="primary" onClick={onClose}>
                Basla
              </Button>
              <Button variant="ghost" onClick={onClose}>
                Gec
              </Button>
            </div>
          </div>
          <div className={`flex items-center justify-center ${reduceMotion ? "" : "elyan-float"}`}>
            <img
              src={heroImage}
              alt="Elyan welcome"
              className="h-[240px] w-[240px] rounded-[28px] object-contain shadow-[0_18px_48px_rgba(49,74,144,0.14)]"
            />
          </div>
        </div>
      </div>
    </div>
  );
}
