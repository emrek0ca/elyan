import { Cable, Command, Cpu, Home, Layers3, ShieldCheck, SlidersHorizontal } from "@/vendor/lucide-react";
import { NavLink } from "react-router-dom";

import { ElyanMark } from "@/components/brand/ElyanMark";
import { cn } from "@/utils/cn";

const navItems = [
  { to: "/home", label: "Home", icon: Home },
  { to: "/stack", label: "Stack", icon: Layers3 },
  { to: "/command-center", label: "Work", icon: Command },
  { to: "/providers", label: "Models", icon: Cpu },
  { to: "/integrations", label: "Apps", icon: Cable },
  { to: "/admin", label: "Admin", icon: ShieldCheck },
  { to: "/settings", label: "Settings", icon: SlidersHorizontal },
];

export function SidebarRail() {
  return (
    <aside className="w-[108px] border-r border-[var(--glass-border)] bg-[var(--glass-panel)] px-3 py-5 backdrop-blur-[20px]">
      <div className="mb-6 flex justify-center">
        <ElyanMark size="sm" alt="Elyan" />
      </div>

      <nav className="space-y-2">
        {navItems.map(({ to, label, icon: Icon }) => (
          <NavLink
            key={to}
            to={to}
            className={({ isActive }) =>
              cn(
                "flex flex-col items-center justify-center gap-2 rounded-[18px] border p-3 text-[11px] font-medium tracking-[0.01em] transition-all duration-150 ease-premium",
                isActive
                  ? "border-[var(--glass-border-strong)] bg-[color-mix(in_srgb,var(--accent-soft)_76%,white)] text-[var(--accent-primary)] shadow-[0_14px_28px_var(--accent-glow)]"
                  : "border-transparent text-[var(--text-secondary)] hover:border-[var(--glass-border)] hover:bg-[var(--glass-elevated)] hover:text-[var(--text-primary)]",
              )
            }
            aria-label={label}
            title={label}
          >
            <Icon className="h-4 w-4 shrink-0" />
            <span>{label}</span>
          </NavLink>
        ))}
      </nav>
    </aside>
  );
}
