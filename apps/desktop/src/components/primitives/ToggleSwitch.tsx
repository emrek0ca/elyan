type ToggleSwitchProps = {
  checked: boolean;
  onChange: (value: boolean) => void;
  label: string;
  description?: string;
};

export function ToggleSwitch({ checked, onChange, label, description }: ToggleSwitchProps) {
  return (
    <button
      type="button"
      role="switch"
      aria-checked={checked}
      onClick={() => onChange(!checked)}
      className="flex w-full items-center justify-between rounded-md border border-[var(--border-subtle)] bg-[var(--bg-surface)] px-4 py-3 text-left shadow-panel transition-all duration-150 ease-premium hover:-translate-y-[1px] focus-visible:focus-ring"
    >
      <div>
        <div className="text-[13px] font-medium text-[var(--text-primary)]">{label}</div>
        {description ? <div className="text-[11px] text-[var(--text-tertiary)]">{description}</div> : null}
      </div>
      <span
        className={`relative h-6 w-11 rounded-full transition-colors ${checked ? "bg-[var(--accent-primary)]" : "bg-[var(--border-strong)]"}`}
      >
        <span
          className={`absolute top-1 h-4 w-4 rounded-full bg-white transition-transform ${checked ? "translate-x-6" : "translate-x-1"}`}
        />
      </span>
    </button>
  );
}

