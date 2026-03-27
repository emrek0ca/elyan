export function SkeletonBlock({ className = "h-24 w-full" }: { className?: string }) {
  return (
    <div
      className={`${className} animate-pulse rounded-md border border-[var(--border-subtle)] bg-[linear-gradient(110deg,color-mix(in_srgb,var(--bg-surface-alt)_88%,transparent),color-mix(in_srgb,var(--bg-surface)_95%,transparent),color-mix(in_srgb,var(--bg-surface-alt)_88%,transparent))] bg-[length:200%_100%] shadow-panel`}
    />
  );
}

