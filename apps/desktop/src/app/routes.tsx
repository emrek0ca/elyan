import { Suspense, lazy, type ReactNode } from "react";
import { Navigate, createHashRouter } from "react-router-dom";

import { AppShell } from "@/shell/AppShell";
import { useUiStore } from "@/stores/ui-store";

const LoginScreen = lazy(() => import("@/screens/auth/LoginScreen").then((module) => ({ default: module.LoginScreen })));
const AdminScreen = lazy(() => import("@/screens/admin/AdminScreen").then((module) => ({ default: module.AdminScreen })));
const CommandCenterScreen = lazy(() =>
  import("@/screens/command-center/CommandCenterScreen").then((module) => ({ default: module.CommandCenterScreen })),
);
const RouteErrorScreen = lazy(() => import("@/screens/error/RouteErrorScreen").then((module) => ({ default: module.RouteErrorScreen })));
const HomeScreen = lazy(() => import("@/screens/home/HomeScreen").then((module) => ({ default: module.HomeScreen })));
const IntegrationsScreen = lazy(() =>
  import("@/screens/integrations/IntegrationsScreen").then((module) => ({ default: module.IntegrationsScreen })),
);
const LogsScreen = lazy(() => import("@/screens/activity-logs/LogsScreen").then((module) => ({ default: module.LogsScreen })));
const OnboardingScreen = lazy(() =>
  import("@/screens/onboarding/OnboardingScreen").then((module) => ({ default: module.OnboardingScreen })),
);
const ProvidersScreen = lazy(() =>
  import("@/screens/providers/ProvidersScreen").then((module) => ({ default: module.ProvidersScreen })),
);
const SettingsScreen = lazy(() => import("@/screens/settings/SettingsScreen").then((module) => ({ default: module.SettingsScreen })));

function RouteFallback() {
  return (
    <div className="flex min-h-[220px] items-center justify-center rounded-[24px] border border-[var(--glass-border)] bg-[var(--glass-elevated)] text-[13px] text-[var(--text-secondary)]">
      Yukleniyor
    </div>
  );
}

function withSuspense(node: ReactNode) {
  return <Suspense fallback={<RouteFallback />}>{node}</Suspense>;
}

function IndexRedirect() {
  const onboardingComplete = useUiStore((state) => state.onboardingComplete);
  const isAuthenticated = useUiStore((state) => state.isAuthenticated);
  if (!onboardingComplete) {
    return <Navigate to="/onboarding" replace />;
  }
  return <Navigate to={isAuthenticated ? "/home" : "/login"} replace />;
}

function LoginRoute() {
  const onboardingComplete = useUiStore((state) => state.onboardingComplete);
  const isAuthenticated = useUiStore((state) => state.isAuthenticated);
  if (!isAuthenticated) {
    return withSuspense(<LoginScreen />);
  }
  return <Navigate to={onboardingComplete ? "/home" : "/onboarding"} replace />;
}

function ProtectedShell() {
  const isAuthenticated = useUiStore((state) => state.isAuthenticated);
  return isAuthenticated ? <AppShell /> : <Navigate to="/login" replace />;
}

function OnboardingRoute() {
  const onboardingComplete = useUiStore((state) => state.onboardingComplete);
  const isAuthenticated = useUiStore((state) => state.isAuthenticated);
  if (onboardingComplete) {
    return <Navigate to={isAuthenticated ? "/home" : "/login"} replace />;
  }
  return withSuspense(<OnboardingScreen />);
}

export const router = createHashRouter([
  {
    path: "/",
    element: <IndexRedirect />,
    errorElement: withSuspense(<RouteErrorScreen />),
  },
  {
    path: "/login",
    element: <LoginRoute />,
    errorElement: withSuspense(<RouteErrorScreen />),
  },
  {
    path: "/onboarding",
    element: <OnboardingRoute />,
    errorElement: withSuspense(<RouteErrorScreen />),
  },
  {
    element: <ProtectedShell />,
    errorElement: withSuspense(<RouteErrorScreen />),
    children: [
      { path: "/home", element: withSuspense(<HomeScreen />) },
      { path: "/command-center", element: withSuspense(<CommandCenterScreen />) },
      { path: "/providers", element: withSuspense(<ProvidersScreen />) },
      { path: "/integrations", element: withSuspense(<IntegrationsScreen />) },
      { path: "/admin", element: withSuspense(<AdminScreen />) },
      { path: "/settings", element: withSuspense(<SettingsScreen />) },
      { path: "/logs", element: withSuspense(<LogsScreen />) },
    ],
  },
]);
