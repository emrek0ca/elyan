import { ElyanMark } from "@/components/brand/ElyanMark";

export function SplashScreen({ visible, stage }: { visible: boolean; stage: string }) {
  if (!visible) {
    return null;
  }

  return (
    <div className="fixed inset-0 z-[100] flex items-center justify-center bg-[var(--bg-shell)]">
      <div className="flex max-w-2xl flex-col items-center gap-8 px-6">
        <ElyanMark size="xl" className="h-[180px] w-[180px] rounded-[36px]" alt="Elyan logo" />
        <div className="space-y-2 text-center">
          <div className="font-display text-[34px] font-semibold tracking-[-0.05em] text-[var(--text-primary)]">Elyan</div>
        </div>
        <div className="h-1.5 w-56 overflow-hidden rounded-full bg-[var(--accent-soft)]">
          <div className="elyan-progress h-full rounded-full bg-[var(--accent-primary)]" />
        </div>
        <div className="text-[12px] text-[var(--text-tertiary)]">{stage}</div>
      </div>
    </div>
  );
}
