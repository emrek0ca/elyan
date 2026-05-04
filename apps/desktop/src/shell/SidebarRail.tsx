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
      "flex items-center gap-3 rounded-[10px] border px-3 py-3 text-[12px] font-medium transition-all duration-150 ease-premium",
      isActive
        ? "border-[var(--glass-border-strong)] bg-[var(--accent-soft)] text-[var(--accent-primary)]"
        : "border-transparent text-[var(--text-secondary)] hover:border-[var(--glass-border)] hover:bg-[var(--glass-elevated)] hover:text-[var(--text-primary)]",
    );

  return (
    <aside className="w-[208px] border-r border-[var(--glass-border)] bg-[var(--glass-panel)] px-4 py-5">
      <div className="mb-6 flex items-center gap-3 px-2">
        <ElyanMark size="sm" alt="Elyan" />
        <div className="text-[12px] font-medium text-[var(--text-primary)]">Elyan</div>
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
