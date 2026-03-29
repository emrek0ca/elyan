import { ElyanMark } from "@/components/brand/ElyanMark";
import { closeWindow, minimizeWindow, toggleMaximizeWindow } from "@/services/desktop/window";

function detectMac() {
  if (typeof navigator === "undefined") {
    return false;
  }
  return /mac/i.test(navigator.platform);
}

export function TitleBar() {
  const mac = detectMac();

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
        </div>
      </div>
      <div className="flex items-center gap-2">{!mac ? controls : null}</div>
    </header>
  );
}
