import { useState } from "react";
import { Command } from "@/vendor/lucide-react";

import { Button } from "@/components/primitives/Button";
import { StatusBadge } from "@/components/primitives/StatusBadge";
import { Surface } from "@/components/primitives/Surface";
import { useRuntimeStore } from "@/stores/runtime-store";
import { useUiStore } from "@/stores/ui-store";

export function TopCommandBar() {
  const [value] = useState("");
  const connectionState = useRuntimeStore((state) => state.connectionState);
  const sidecarHealth = useRuntimeStore((state) => state.sidecarHealth);
  const openCommandPalette = useUiStore((state) => state.openCommandPalette);

  return (
    <Surface tone="panel" className="mb-7 px-5 py-4">
      <div className="flex items-center justify-between gap-3">
        <div className="text-[12px] text-[var(--text-secondary)]">{value || "Tek odak, görünür durum."}</div>
        <div className="flex shrink-0 items-center gap-2">
          <StatusBadge
            tone={
              connectionState === "connected"
                ? "success"
                : connectionState === "booting" || connectionState === "reconnecting"
                  ? "warning"
                  : "error"
            }
          >
            {connectionState === "connected"
              ? sidecarHealth.managed
                ? "ready"
                : "external"
              : connectionState.replace(/_/g, " ")}
          </StatusBadge>
          <Button variant="secondary" size="sm" onClick={() => openCommandPalette()}>
            <Command className="mr-2 h-4 w-4" />
            Command
          </Button>
        </div>
      </div>
    </Surface>
  );
}
