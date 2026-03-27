import { useEffect, useMemo, useState } from "react";
import { RouterProvider } from "react-router-dom";

import { router } from "@/app/routes";
import { SplashScreen } from "@/screens/splash/SplashScreen";
import { useUiStore } from "@/stores/ui-store";

function resolveTheme(mode: "light" | "dark" | "system") {
  if (mode === "system") {
    return window.matchMedia("(prefers-color-scheme: dark)").matches ? "dark" : "light";
  }
  return mode;
}

export function App() {
  const [splashVisible, setSplashVisible] = useState(true);
  const themeMode = useUiStore((state) => state.themeMode);

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
    <>
      <RouterProvider router={router} />
      <SplashScreen visible={splashVisible} />
    </>
  );
}

