import type { CommandCenterSnapshot } from "@/types/domain";
import { Surface } from "@/components/primitives/Surface";
import { StatusBadge } from "@/components/primitives/StatusBadge";

const toneMap = {
  thinking: "info",
  action: "neutral",
  result: "success",
  evidence: "neutral",
  warning: "warning",
} as const;

export function OutputStream({ outputBlocks }: Pick<CommandCenterSnapshot, "outputBlocks">) {
  return (
    <div className="space-y-4">
      {outputBlocks.map((block: CommandCenterSnapshot["outputBlocks"][number]) => (
        <Surface key={block.id} tone="card" className="p-5">
          <div className="mb-3 flex items-center justify-between gap-3">
            <div className="text-[14px] font-medium text-[var(--text-primary)]">{block.title}</div>
            <StatusBadge tone={toneMap[block.kind]}>{block.kind}</StatusBadge>
          </div>
          <p className="text-[13px] leading-6 text-[var(--text-secondary)]">{block.body}</p>
          {block.meta ? <div className="mt-3 text-[11px] text-[var(--text-tertiary)]">{block.meta}</div> : null}
        </Surface>
      ))}
    </div>
  );
}
