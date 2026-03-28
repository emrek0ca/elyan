import { useState } from "react";
import { Sparkles } from "lucide-react";

import { Button } from "@/components/primitives/Button";
import { SearchField } from "@/components/primitives/SearchField";
import { StatusBadge } from "@/components/primitives/StatusBadge";
import { Surface } from "@/components/primitives/Surface";
import { useRuntimeStore } from "@/stores/runtime-store";
import { useUiStore } from "@/stores/ui-store";

export function TopCommandBar() {
  const [value, setValue] = useState("");
  const openCommandPalette = useUiStore((state) => state.openCommandPalette);
  const connectionState = useRuntimeStore((state) => state.connectionState);
  const sidecarHealth = useRuntimeStore((state) => state.sidecarHealth);

  return (
    <Surface tone="panel" className="mb-7 px-4 py-4">
      <div className="flex items-center gap-3">
        <div className="min-w-0 flex-1">
          <SearchField
            value={value}
            onChange={(event) => setValue(event.target.value)}
            placeholder="Ask Elyan to create, continue, or review"
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
            {connectionState === "connected"
              ? sidecarHealth.managed
                ? "runtime ready"
                : "external runtime"
              : connectionState.replace(/_/g, " ")}
          </StatusBadge>
          <Button variant="secondary" onClick={() => openCommandPalette()}>
            <Sparkles className="mr-2 h-4 w-4" />
            Command
          </Button>
        </div>
      </div>
    </Surface>
  );
}
