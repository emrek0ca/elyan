import { useEffect, useMemo, useState } from "react";
import { useLocation, useNavigate } from "react-router-dom";

import { SearchField } from "@/components/primitives/SearchField";
import { useUiStore } from "@/stores/ui-store";

const commands = [
  { id: "home", label: "Go to Home", route: "/home", hint: "Main dashboard" },
  { id: "command", label: "Open Command Center", route: "/command-center", hint: "Run and inspect tasks" },
  { id: "models", label: "Open Models", route: "/providers", hint: "Provider management" },
  { id: "integrations", label: "Open Integrations", route: "/integrations", hint: "Connections and devices" },
  { id: "admin", label: "Open Admin", route: "/admin", hint: "Workspace, billing and learning pulse" },
  { id: "settings", label: "Open Settings", route: "/settings", hint: "Appearance, models, security" },
  { id: "logs", label: "Open Logs", route: "/logs", hint: "Monitoring and diagnostics" },
];

export function CommandPalette() {
  const open = useUiStore((state) => state.commandPaletteOpen);
  const close = useUiStore((state) => state.closeCommandPalette);
  const navigate = useNavigate();
  const location = useLocation();
  const [query, setQuery] = useState("");

  useEffect(() => {
    if (!open) {
      setQuery("");
    }
  }, [open]);

  const filtered = useMemo(() => {
    if (!query.trim()) {
      return commands;
    }
    return commands.filter((command) =>
      `${command.label} ${command.hint}`.toLowerCase().includes(query.toLowerCase()),
    );
  }, [query]);

  useEffect(() => {
    const onKey = (event: KeyboardEvent) => {
      if (event.key === "Escape") {
        close();
      }
    };
    if (open) {
      window.addEventListener("keydown", onKey);
    }
    return () => window.removeEventListener("keydown", onKey);
  }, [open, close]);

  if (!open) {
    return null;
  }

  return (
    <div
      className="fixed inset-0 z-50 flex items-start justify-center bg-[var(--bg-overlay)] px-6 pt-20 backdrop-blur-sm"
      onClick={() => close()}
    >
      <div
        className="w-full max-w-2xl rounded-xl border border-[var(--border-subtle)] bg-[var(--bg-shell)] p-4 shadow-elevated"
        onClick={(event) => event.stopPropagation()}
      >
        <SearchField
          autoFocus
          value={query}
          onChange={(event) => setQuery(event.target.value)}
          placeholder="Search commands, screens, and actions"
        />
        <div className="mt-4 space-y-2">
          {filtered.map((command) => (
            <button
              key={command.id}
              type="button"
              onClick={() => {
                navigate(command.route);
                close();
              }}
              className={`flex w-full items-center justify-between rounded-md border px-4 py-3 text-left transition-all duration-150 ease-premium ${
                location.pathname === command.route
                  ? "border-[var(--border-focus)] bg-[var(--accent-soft)]"
                  : "border-[var(--border-subtle)] bg-[var(--bg-surface)] hover:-translate-y-[1px]"
              }`}
            >
              <div>
                <div className="text-[13px] font-medium text-[var(--text-primary)]">{command.label}</div>
                <div className="text-[11px] text-[var(--text-tertiary)]">{command.hint}</div>
              </div>
              <div className="text-[11px] text-[var(--text-tertiary)]">↵</div>
            </button>
          ))}
        </div>
      </div>
    </div>
  );
}
