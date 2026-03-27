import type { ActivityItem } from "@/types/domain";
import { Surface } from "@/components/primitives/Surface";
import { StatusBadge } from "@/components/primitives/StatusBadge";

export function ActivityFeed({ items }: { items: ActivityItem[] }) {
  return (
    <div className="space-y-3">
      {items.map((item) => (
        <Surface key={item.id} tone="card" className="p-4">
          <div className="flex items-start justify-between gap-4">
            <div className="space-y-1">
              <div className="text-[13px] font-medium text-[var(--text-primary)]">{item.title}</div>
              <div className="text-[12px] text-[var(--text-secondary)]">{item.detail}</div>
            </div>
            <StatusBadge tone={item.level === "error" ? "error" : item.level === "warning" ? "warning" : item.level === "success" ? "success" : "info"}>
              {item.createdAt}
            </StatusBadge>
          </div>
        </Surface>
      ))}
    </div>
  );
}

