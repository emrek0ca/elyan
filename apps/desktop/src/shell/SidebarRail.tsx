import { Bot, Cable, Command, Home, Logs, Settings2, SlidersHorizontal } from "lucide-react";
import { NavLink } from "react-router-dom";

import { Button } from "@/components/primitives/Button";
import { StatusBadge } from "@/components/primitives/StatusBadge";
import { useUiStore } from "@/stores/ui-store";
import { cn } from "@/utils/cn";

const navItems = [
  { to: "/home", label: "Home", icon: Home },
  { to: "/command-center", label: "Command Center", icon: Command },
  { to: "/providers", label: "Models", icon: Bot },
  { to: "/integrations", label: "Integrations", icon: Cable },
  { to: "/settings", label: "Settings", icon: SlidersHorizontal },
  { to: "/logs", label: "Logs", icon: Logs },
];

export function SidebarRail() {
  const collapsed = useUiStore((state) => state.sidebarCollapsed);
  const toggleSidebar = useUiStore((state) => state.toggleSidebar);

  return (
    <aside
      className={cn(
        "border-r border-[var(--border-subtle)] bg-[color-mix(in_srgb,var(--bg-shell)_96%,transparent)] px-4 py-5 transition-all duration-180 ease-premium",
        collapsed ? "w-[92px]" : "w-[248px]",
      )}
    >
      <div className="mb-8 flex items-start justify-between gap-3">
        <div className={cn("space-y-3", collapsed && "hidden")}>
          <div className="flex items-center gap-3">
            <div className="flex h-11 w-11 items-center justify-center rounded-[18px] border border-[color-mix(in_srgb,var(--accent-primary)_18%,var(--border-subtle))] bg-[linear-gradient(180deg,color-mix(in_srgb,var(--accent-soft)_80%,white),var(--bg-surface))] text-[13px] font-semibold tracking-[0.18em] text-[var(--accent-primary)]">
              EL
            </div>
            <div>
              <div className="text-[10px] uppercase tracking-[0.2em] text-[var(--text-tertiary)]">Elyan</div>
              <div className="mt-1 font-display text-[19px] font-semibold tracking-[-0.04em] text-[var(--text-primary)]">
                Operating layer
              </div>
            </div>
          </div>
          <StatusBadge tone="success">Calm shell</StatusBadge>
        </div>
        <Button variant="ghost" size="sm" onClick={() => toggleSidebar()}>
          {collapsed ? "»" : "«"}
        </Button>
      </div>

      <nav className="space-y-2">
        {navItems.map(({ to, label, icon: Icon }) => (
          <NavLink
            key={to}
            to={to}
            className={({ isActive }) =>
              cn(
                "flex items-center gap-3 rounded-[18px] border border-transparent px-3 py-3 text-[13px] font-medium transition-all duration-150 ease-premium",
                isActive
                  ? "border-[color-mix(in_srgb,var(--accent-primary)_12%,transparent)] bg-[color-mix(in_srgb,var(--accent-soft)_84%,white)] text-[var(--accent-primary)]"
                  : "text-[var(--text-secondary)] hover:bg-[var(--bg-surface)] hover:text-[var(--text-primary)]",
              )
            }
          >
            <Icon className="h-4 w-4 shrink-0" />
            {!collapsed ? <span>{label}</span> : null}
          </NavLink>
        ))}
      </nav>

      <div className="mt-8 rounded-[20px] border border-[var(--border-subtle)] bg-[var(--bg-surface)] p-4 shadow-panel">
        <div className={cn("space-y-2", collapsed && "hidden")}>
          <div className="text-[11px] uppercase tracking-[0.16em] text-[var(--text-tertiary)]">Workspace</div>
          <div className="text-[13px] font-medium text-[var(--text-primary)]">Local runtime lane</div>
          <div className="text-[11px] leading-5 text-[var(--text-secondary)]">Primary command surface, keyboard-first flow, managed sidecar.</div>
          <StatusBadge tone="info">Keyboard first</StatusBadge>
        </div>
      </div>
    </aside>
  );
}
