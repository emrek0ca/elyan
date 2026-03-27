import { useState } from "react";
import { ArrowRight, Sparkles } from "lucide-react";
import { useNavigate } from "react-router-dom";

import { Button } from "@/components/primitives/Button";
import { SearchField } from "@/components/primitives/SearchField";
import { StatusBadge } from "@/components/primitives/StatusBadge";
import { Surface } from "@/components/primitives/Surface";
import { useRuntimeStore } from "@/stores/runtime-store";
import { useUiStore } from "@/stores/ui-store";

export function TopCommandBar() {
  const [value, setValue] = useState("");
  const navigate = useNavigate();
  const openCommandPalette = useUiStore((state) => state.openCommandPalette);
  const connectionState = useRuntimeStore((state) => state.connectionState);
  const sidecarHealth = useRuntimeStore((state) => state.sidecarHealth);

  return (
    <Surface tone="panel" className="mb-7 px-5 py-4">
      <div className="flex items-center gap-4">
        <div className="min-w-0 flex-1">
          <div className="mb-2 flex items-center justify-between gap-3">
            <div className="text-[11px] uppercase tracking-[0.16em] text-[var(--text-tertiary)]">Global command bar</div>
            <div className="hidden items-center gap-2 text-[11px] text-[var(--text-tertiary)] xl:flex">
              <span>{sidecarHealth.managed ? `managed sidecar · ${sidecarHealth.port}` : `external runtime · ${sidecarHealth.port}`}</span>
              <kbd className="rounded-full border border-[var(--border-subtle)] bg-[var(--bg-surface)] px-2 py-1 font-mono text-[10px] text-[var(--text-secondary)]">⌘K</kbd>
            </div>
          </div>
          <SearchField
            value={value}
            onChange={(event) => setValue(event.target.value)}
            placeholder="Ask Elyan to create, review, or continue a workflow"
            className="h-12 flex-1 shadow-none"
          />
        </div>
        <div className="flex shrink-0 items-center gap-3">
          <StatusBadge
            tone={
              connectionState === "connected"
                ? "success"
                : connectionState === "booting" || connectionState === "reconnecting"
                  ? "warning"
                  : "error"
            }
          >
            {connectionState === "connected" ? "runtime online" : connectionState.replace(/_/g, " ")}
          </StatusBadge>
          <Button variant="secondary" onClick={() => openCommandPalette()}>
            <Sparkles className="mr-2 h-4 w-4" />
            Quick actions
          </Button>
          <Button
            variant="primary"
            onClick={() => {
              navigate("/command-center");
              setValue("");
            }}
          >
            Open run
            <ArrowRight className="ml-2 h-4 w-4" />
          </Button>
        </div>
      </div>
    </Surface>
  );
}
