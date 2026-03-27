import { cn } from "@/utils/cn";

type Option = { label: string; value: string };

type SegmentedControlProps = {
  value: string;
  onChange: (value: string) => void;
  options: Option[];
};

export function SegmentedControl({ value, onChange, options }: SegmentedControlProps) {
  return (
    <div className="inline-flex rounded-full border border-[var(--border-subtle)] bg-[var(--bg-surface)] p-1 shadow-panel">
      {options.map((option) => {
        const active = option.value === value;
        return (
          <button
            key={option.value}
            type="button"
            onClick={() => onChange(option.value)}
            className={cn(
              "rounded-full px-3 py-1.5 text-[11px] font-medium transition-all duration-150 ease-premium focus-visible:focus-ring",
              active
                ? "bg-[var(--accent-soft)] text-[var(--accent-primary)]"
                : "text-[var(--text-secondary)] hover:text-[var(--text-primary)]",
            )}
          >
            {option.label}
          </button>
        );
      })}
    </div>
  );
}

