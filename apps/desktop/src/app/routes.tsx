import { Navigate, createHashRouter } from "react-router-dom";

import { AppShell } from "@/shell/AppShell";
import { LoginScreen } from "@/screens/auth/LoginScreen";
import { CommandCenterScreen } from "@/screens/command-center/CommandCenterScreen";
import { RouteErrorScreen } from "@/screens/error/RouteErrorScreen";
import { HomeScreen } from "@/screens/home/HomeScreen";
import { IntegrationsScreen } from "@/screens/integrations/IntegrationsScreen";
import { LogsScreen } from "@/screens/logs/LogsScreen";
import { OnboardingScreen } from "@/screens/onboarding/OnboardingScreen";
import { ProvidersScreen } from "@/screens/providers/ProvidersScreen";
import { SettingsScreen } from "@/screens/settings/SettingsScreen";
import { useUiStore } from "@/stores/ui-store";

function IndexRedirect() {
  const isAuthenticated = useUiStore((state) => state.isAuthenticated);
  return <Navigate to={isAuthenticated ? "/home" : "/login"} replace />;
}

function LoginRoute() {
  const isAuthenticated = useUiStore((state) => state.isAuthenticated);
  return isAuthenticated ? <Navigate to="/home" replace /> : <LoginScreen />;
}

function ProtectedShell() {
  const isAuthenticated = useUiStore((state) => state.isAuthenticated);
  return isAuthenticated ? <AppShell /> : <Navigate to="/login" replace />;
}

export const router = createHashRouter([
  {
    path: "/",
    element: <IndexRedirect />,
    errorElement: <RouteErrorScreen />,
  },
  {
    path: "/login",
    element: <LoginRoute />,
    errorElement: <RouteErrorScreen />,
  },
  {
    path: "/onboarding",
    element: <OnboardingScreen />,
    errorElement: <RouteErrorScreen />,
  },
  {
    element: <ProtectedShell />,
    errorElement: <RouteErrorScreen />,
    children: [
      { path: "/home", element: <HomeScreen /> },
      { path: "/command-center", element: <CommandCenterScreen /> },
      { path: "/providers", element: <ProvidersScreen /> },
      { path: "/integrations", element: <IntegrationsScreen /> },
      { path: "/settings", element: <SettingsScreen /> },
      { path: "/logs", element: <LogsScreen /> },
    ],
  },
]);
