import { Navigate, createHashRouter } from "react-router-dom";

import { AppShell } from "@/shell/AppShell";
import { CommandCenterScreen } from "@/screens/command-center/CommandCenterScreen";
import { HomeScreen } from "@/screens/home/HomeScreen";
import { IntegrationsScreen } from "@/screens/integrations/IntegrationsScreen";
import { LogsScreen } from "@/screens/logs/LogsScreen";
import { OnboardingScreen } from "@/screens/onboarding/OnboardingScreen";
import { ProvidersScreen } from "@/screens/providers/ProvidersScreen";
import { SettingsScreen } from "@/screens/settings/SettingsScreen";
import { useUiStore } from "@/stores/ui-store";

function IndexRedirect() {
  const onboardingComplete = useUiStore((state) => state.onboardingComplete);
  return <Navigate to={onboardingComplete ? "/home" : "/onboarding"} replace />;
}

export const router = createHashRouter([
  {
    path: "/",
    element: <IndexRedirect />,
  },
  {
    path: "/onboarding",
    element: <OnboardingScreen />,
  },
  {
    element: <AppShell />,
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

