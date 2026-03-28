import { useRouteError } from "react-router-dom";

import { Button } from "@/components/primitives/Button";
import { Surface } from "@/components/primitives/Surface";

export function RouteErrorScreen() {
  const error = useRouteError() as { message?: string; statusText?: string } | undefined;
  const detail = error?.message || error?.statusText || "Beklenmeyen bir hata oluştu.";

  return (
    <div className="flex min-h-screen items-center justify-center px-6 py-10">
      <Surface tone="card" className="w-full max-w-[560px] px-8 py-8">
        <div className="space-y-4">
          <div className="text-[11px] uppercase tracking-[0.18em] text-[var(--text-tertiary)]">Elyan</div>
          <h1 className="font-display text-[30px] font-semibold tracking-[-0.04em] text-[var(--text-primary)]">
            Uygulama durdu
          </h1>
          <p className="text-[14px] leading-7 text-[var(--text-secondary)]">{detail}</p>
          <div>
            <Button variant="primary" onClick={() => window.location.reload()}>
              Yeniden yükle
            </Button>
          </div>
        </div>
      </Surface>
    </div>
  );
}
