import { Cable, Command, Cpu, Home, Layers3, ShieldCheck, SlidersHorizontal, Waypoints } from "@/vendor/lucide-react";
import { NavLink } from "react-router-dom";

import { ElyanMark } from "@/components/brand/ElyanMark";
import { cn } from "@/utils/cn";

const primaryItems = [
  { to: "/home", label: "Home", icon: Home },
  { to: "/command-center", label: "Work", icon: Command },
  { to: "/integrations", label: "Apps", icon: Cable },
  { to: "/settings", label: "Settings", icon: SlidersHorizontal },
];

const secondaryItems = [
  { to: "/stack", label: "Stack", icon: Layers3 },
  { to: "/swarm", label: "Swarm", icon: Waypoints },
  { to: "/providers", label: "Models", icon: Cpu },
  { to: "/admin", label: "Admin", icon: ShieldCheck },
];

export function SidebarRail() {
  const linkClassName = ({ isActive }: { isActive: boolean }) =>
    cn(
      "flex items-center gap-3 rounded-[16px] border px-3 py-3 text-[12px] font-medium transition-all duration-150 ease-premium",
      isActive
        ? "border-[var(--glass-border-strong)] bg-[color-mix(in_srgb,var(--accent-soft)_76%,white)] text-[var(--accent-primary)] shadow-[0_10px_24px_var(--accent-glow)]"
        : "border-transparent text-[var(--text-secondary)] hover:border-[var(--glass-border)] hover:bg-[var(--glass-elevated)] hover:text-[var(--text-primary)]",
    );

  return (
    <aside className="w-[224px] border-r border-[var(--glass-border)] bg-[var(--glass-panel)] px-4 py-5 backdrop-blur-[20px]">
      <div className="mb-6 flex items-center gap-3 px-2">
        <ElyanMark size="sm" alt="Elyan" />
        <div>
          <div className="text-[12px] font-medium text-[var(--text-primary)]">Elyan</div>
          <div className="text-[11px] text-[var(--text-tertiary)]">local operator</div>
        </div>
      </div>

      <nav className="space-y-2">
        {primaryItems.map(({ to, label, icon: Icon }) => (
          <NavLink
            key={to}
            to={to}
            className={linkClassName}
            aria-label={label}
            title={label}
          >
            <Icon className="h-4 w-4 shrink-0" />
            <span>{label}</span>
          </NavLink>
        ))}
      </nav>

      <div className="mt-6 border-t border-[var(--glass-border)] pt-4">
        <div className="px-2 pb-2 text-[10px] uppercase tracking-[0.16em] text-[var(--text-tertiary)]">Advanced</div>
        <nav className="space-y-2">
          {secondaryItems.map(({ to, label, icon: Icon }) => (
            <NavLink
              key={to}
              to={to}
              className={linkClassName}
              aria-label={label}
              title={label}
            >
              <Icon className="h-4 w-4 shrink-0" />
              <span>{label}</span>
            </NavLink>
          ))}
        </nav>
      </div>
    </aside>
  );
}
