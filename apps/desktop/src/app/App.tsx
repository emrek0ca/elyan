import { Component, type ErrorInfo, type ReactNode, useEffect, useMemo, useState } from "react";
import { RouterProvider } from "react-router-dom";

import { router } from "@/app/routes";
import { Button } from "@/components/primitives/Button";
import { Surface } from "@/components/primitives/Surface";
import { useSystemReadiness } from "@/hooks/use-desktop-data";
import { SplashScreen } from "@/screens/splash/SplashScreen";
import { useUiStore } from "@/stores/ui-store";

function resolveTheme(mode: "light" | "dark" | "system") {
  if (mode === "system") {
    return window.matchMedia("(prefers-color-scheme: dark)").matches ? "dark" : "light";
  }
  return mode;
}

type AppErrorBoundaryProps = {
  children: ReactNode;
};

type AppErrorBoundaryState = {
  hasError: boolean;
  detail: string;
};

class AppErrorBoundary extends Component<AppErrorBoundaryProps, AppErrorBoundaryState> {
  state: AppErrorBoundaryState = {
    hasError: false,
    detail: "",
  };

  static getDerivedStateFromError(error: unknown): AppErrorBoundaryState {
    return {
      hasError: true,
      detail: error instanceof Error ? error.message : "Beklenmeyen bir hata oluştu.",
    };
  }

  componentDidCatch(error: unknown, errorInfo: ErrorInfo) {
    console.error("AppErrorBoundary", error, errorInfo);
  }

  render() {
    if (this.state.hasError) {
      return (
        <div className="flex min-h-screen items-center justify-center px-6 py-10">
          <Surface tone="card" className="w-full max-w-[560px] px-8 py-8">
            <div className="space-y-4">
              <div className="text-[11px] uppercase tracking-[0.18em] text-[var(--text-tertiary)]">Elyan</div>
              <h1 className="font-display text-[30px] font-semibold tracking-[-0.04em] text-[var(--text-primary)]">
                Uygulama durdu
              </h1>
              <p className="text-[14px] leading-7 text-[var(--text-secondary)]">{this.state.detail || "Beklenmeyen bir hata oluştu."}</p>
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
    return this.props.children;
  }
}

export function App() {
  const [splashVisible, setSplashVisible] = useState(true);
  const themeMode = useUiStore((state) => state.themeMode);
  const { data: readiness } = useSystemReadiness();

  const effectiveTheme = useMemo(() => resolveTheme(themeMode), [themeMode]);

  useEffect(() => {
    document.documentElement.dataset.theme = effectiveTheme;
  }, [effectiveTheme]);

  useEffect(() => {
    const timer = window.setTimeout(() => setSplashVisible(false), 1650);
    return () => window.clearTimeout(timer);
  }, []);

  useEffect(() => {
    const onKeyDown = (event: KeyboardEvent) => {
      if ((event.metaKey || event.ctrlKey) && event.key.toLowerCase() === "k") {
        event.preventDefault();
        useUiStore.getState().openCommandPalette();
      }
    };
    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  }, []);

  return (
    <AppErrorBoundary>
      <RouterProvider router={router} />
      <SplashScreen visible={splashVisible} stage={String(readiness?.bootStage || "starting_services").replace(/_/g, " ")} />
    </AppErrorBoundary>
  );
}
