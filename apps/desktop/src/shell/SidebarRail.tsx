import { Cable, Command, Home, SlidersHorizontal } from "lucide-react";
import { NavLink } from "react-router-dom";

import { ElyanMark } from "@/components/brand/ElyanMark";
import { Button } from "@/components/primitives/Button";
import { useUiStore } from "@/stores/ui-store";
import { cn } from "@/utils/cn";

const navItems = [
  { to: "/home", label: "Home", icon: Home },
  { to: "/command-center", label: "Work", icon: Command },
  { to: "/integrations", label: "Apps", icon: Cable },
  { to: "/settings", label: "Settings", icon: SlidersHorizontal },
];

export function SidebarRail() {
  const collapsed = useUiStore((state) => state.sidebarCollapsed);
  const toggleSidebar = useUiStore((state) => state.toggleSidebar);

  return (
    <aside
      className={cn("border-r border-[var(--border-subtle)] bg-[color-mix(in_srgb,var(--bg-shell)_96%,transparent)] px-4 py-5 transition-all duration-180 ease-premium", collapsed ? "w-[86px]" : "w-[198px]")}
    >
      <div className="mb-8 flex items-start justify-between gap-3">
        <div className={cn("space-y-3", collapsed && "hidden")}>
          <div className="flex items-center gap-3">
            <ElyanMark size="sm" />
            <div>
              <div className="text-[10px] uppercase tracking-[0.2em] text-[var(--text-tertiary)]">Elyan</div>
              <div className="mt-1 font-display text-[19px] font-semibold tracking-[-0.04em] text-[var(--text-primary)]">Operator shell</div>
            </div>
          </div>
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
    </aside>
  );
}
