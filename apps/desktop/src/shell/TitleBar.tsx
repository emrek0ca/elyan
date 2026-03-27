import { Monitor, MoonStar, Search, SunMedium } from "lucide-react";

import { Button } from "@/components/primitives/Button";
import { SearchField } from "@/components/primitives/SearchField";
import { closeWindow, minimizeWindow, toggleMaximizeWindow } from "@/services/desktop/window";
import { useUiStore } from "@/stores/ui-store";

function detectMac() {
  if (typeof navigator === "undefined") {
    return false;
  }
  return /mac/i.test(navigator.platform);
}

function nextTheme(mode: "light" | "dark" | "system") {
  if (mode === "system") return "light";
  if (mode === "light") return "dark";
  return "system";
}

export function TitleBar() {
  const mac = detectMac();
  const themeMode = useUiStore((state) => state.themeMode);
  const setThemeMode = useUiStore((state) => state.setThemeMode);
  const openCommandPalette = useUiStore((state) => state.openCommandPalette);

  const ThemeIcon = themeMode === "system" ? Monitor : themeMode === "dark" ? MoonStar : SunMedium;

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
        <div className="hidden max-w-md flex-1 md:block">
          <SearchField
            readOnly
            value=""
            onFocus={() => openCommandPalette()}
            onClick={() => openCommandPalette()}
            placeholder="Search commands, runs, providers"
            className="h-10"
          />
        </div>
      </div>
      <div className="flex items-center gap-2">
        <Button variant="ghost" size="sm" onClick={() => openCommandPalette()}>
          <Search className="mr-2 h-4 w-4" />
          Command palette
        </Button>
        <Button variant="secondary" size="sm" onClick={() => setThemeMode(nextTheme(themeMode))}>
          <ThemeIcon className="mr-2 h-4 w-4" />
          {themeMode}
        </Button>
        <Button variant="secondary" size="sm">
          Workspace
        </Button>
        {!mac ? controls : null}
      </div>
    </header>
  );
}

