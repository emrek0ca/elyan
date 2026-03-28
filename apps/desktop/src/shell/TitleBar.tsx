import { Command } from "lucide-react";

import { ElyanMark } from "@/components/brand/ElyanMark";
import { Button } from "@/components/primitives/Button";
import { closeWindow, minimizeWindow, toggleMaximizeWindow } from "@/services/desktop/window";
import { useUiStore } from "@/stores/ui-store";

function detectMac() {
  if (typeof navigator === "undefined") {
    return false;
  }
  return /mac/i.test(navigator.platform);
}

export function TitleBar() {
  const mac = detectMac();
  const openCommandPalette = useUiStore((state) => state.openCommandPalette);

  const controls = (
    <div className="flex items-center gap-2">
      <button
        type="button"
        onClick={() => minimizeWindow()}
        className="h-8 w-8 rounded-full border border-[var(--border-subtle)] text-[var(--text-secondary)] transition hover:bg-[var(--bg-surface)] focus-visible:focus-ring"
      >
        −
      </button>
      <button
        type="button"
        onClick={() => toggleMaximizeWindow()}
        className="h-8 w-8 rounded-full border border-[var(--border-subtle)] text-[var(--text-secondary)] transition hover:bg-[var(--bg-surface)] focus-visible:focus-ring"
      >
        □
      </button>
      <button
        type="button"
        onClick={() => closeWindow()}
        className="h-8 w-8 rounded-full border border-[color-mix(in_srgb,var(--state-error)_24%,transparent)] text-[var(--state-error)] transition hover:bg-[color-mix(in_srgb,var(--state-error)_14%,transparent)] focus-visible:focus-ring"
      >
        ×
      </button>
    </div>
  );

  return (
    <header data-tauri-drag-region className="eylan-titlebar flex items-center justify-between gap-4">
      <div className="flex min-w-0 flex-1 items-center gap-4">
        {mac ? controls : null}
        <div className="flex items-center gap-3">
          <ElyanMark size="sm" alt="Elyan logo" />
          <div className="hidden md:block">
            <div className="text-[11px] uppercase tracking-[0.16em] text-[var(--text-tertiary)]">Elyan</div>
            <div className="text-[13px] font-medium text-[var(--text-primary)]">Desktop</div>
          </div>
        </div>
      </div>
      <div className="flex items-center gap-2">
        <Button variant="secondary" size="sm" onClick={() => openCommandPalette()}>
          <Command className="mr-2 h-4 w-4" />
          Command
        </Button>
        {!mac ? controls : null}
      </div>
    </header>
  );
}
