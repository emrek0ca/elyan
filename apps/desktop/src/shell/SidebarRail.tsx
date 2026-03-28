import { Cable, Command, Home, SlidersHorizontal } from "lucide-react";
import { NavLink } from "react-router-dom";

import { ElyanMark } from "@/components/brand/ElyanMark";
import { cn } from "@/utils/cn";

const navItems = [
  { to: "/home", label: "Home", icon: Home },
  { to: "/command-center", label: "Work", icon: Command },
  { to: "/integrations", label: "Apps", icon: Cable },
  { to: "/settings", label: "Settings", icon: SlidersHorizontal },
];

export function SidebarRail() {
  return (
    <aside className="w-[152px] border-r border-[var(--border-subtle)] bg-[color-mix(in_srgb,var(--bg-shell)_96%,transparent)] px-4 py-6">
      <div className="mb-10 flex justify-center">
        <ElyanMark size="md" alt="Elyan" />
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
            <span>{label}</span>
          </NavLink>
        ))}
      </nav>
    </aside>
  );
}
