import { create } from "zustand";
import { persist } from "zustand/middleware";

import type { ProjectTemplate, ThemeMode, WorkflowPreferences } from "@/types/domain";
import { defaultProjectTemplates, defaultWorkflowPreferences } from "@/utils/workflow-preferences";

type UiState = {
  themeMode: ThemeMode;
  sidebarCollapsed: boolean;
  inspectorCollapsed: boolean;
  commandPaletteOpen: boolean;
  onboardingComplete: boolean;
  isAuthenticated: boolean;
  authenticatedEmail: string;
  selectedThreadId: string;
  selectedRunId: string;
  autoRouting: boolean;
  compactLogs: boolean;
  reduceMotion: boolean;
  workflowPreferences: WorkflowPreferences;
  projectTemplates: ProjectTemplate[];
  activeProjectTemplateId: string;
  setThemeMode: (mode: ThemeMode) => void;
  toggleSidebar: () => void;
  toggleInspector: () => void;
  openCommandPalette: () => void;
  closeCommandPalette: () => void;
  completeOnboarding: () => void;
  signIn: (email: string) => void;
  signOut: () => void;
  setSelectedRunId: (runId: string) => void;
  clearSelectedRunId: () => void;
  setSelectedThreadId: (threadId: string) => void;
  clearSelectedThreadId: () => void;
  setAutoRouting: (value: boolean) => void;
  setCompactLogs: (value: boolean) => void;
  setReduceMotion: (value: boolean) => void;
  setWorkflowPreferences: (updates: Partial<WorkflowPreferences>) => void;
  setActiveProjectTemplateId: (templateId: string) => void;
};

export const useUiStore = create<UiState>()(
  persist(
    (set) => ({
      themeMode: "system",
      sidebarCollapsed: false,
      inspectorCollapsed: false,
      commandPaletteOpen: false,
      onboardingComplete: false,
      isAuthenticated: false,
      authenticatedEmail: "",
      selectedThreadId: "",
      selectedRunId: "",
      autoRouting: true,
      compactLogs: true,
      reduceMotion: false,
      workflowPreferences: defaultWorkflowPreferences,
      projectTemplates: defaultProjectTemplates,
      activeProjectTemplateId: defaultProjectTemplates[0]?.id || "",
      setThemeMode: (themeMode) => set({ themeMode }),
      toggleSidebar: () => set((state) => ({ sidebarCollapsed: !state.sidebarCollapsed })),
      toggleInspector: () => set((state) => ({ inspectorCollapsed: !state.inspectorCollapsed })),
      openCommandPalette: () => set({ commandPaletteOpen: true }),
      closeCommandPalette: () => set({ commandPaletteOpen: false }),
      completeOnboarding: () => set({ onboardingComplete: true }),
      signIn: (authenticatedEmail) => set({ isAuthenticated: true, authenticatedEmail }),
      signOut: () => set({ isAuthenticated: false, authenticatedEmail: "" }),
      setSelectedThreadId: (selectedThreadId) => set({ selectedThreadId }),
      clearSelectedThreadId: () => set({ selectedThreadId: "" }),
      setSelectedRunId: (selectedRunId) => set({ selectedRunId }),
      clearSelectedRunId: () => set({ selectedRunId: "" }),
      setAutoRouting: (autoRouting) => set({ autoRouting }),
      setCompactLogs: (compactLogs) => set({ compactLogs }),
      setReduceMotion: (reduceMotion) => set({ reduceMotion }),
      setWorkflowPreferences: (updates) =>
        set((state) => ({
          workflowPreferences: {
            ...state.workflowPreferences,
            ...updates,
          },
        })),
      setActiveProjectTemplateId: (activeProjectTemplateId) => set({ activeProjectTemplateId }),
    }),
    {
      name: "elyan-desktop-ui",
      partialize: (state) => ({
        themeMode: state.themeMode,
        sidebarCollapsed: state.sidebarCollapsed,
        inspectorCollapsed: state.inspectorCollapsed,
        onboardingComplete: state.onboardingComplete,
        isAuthenticated: state.isAuthenticated,
        authenticatedEmail: state.authenticatedEmail,
        selectedThreadId: state.selectedThreadId,
        selectedRunId: state.selectedRunId,
        autoRouting: state.autoRouting,
        compactLogs: state.compactLogs,
        reduceMotion: state.reduceMotion,
        workflowPreferences: state.workflowPreferences,
        projectTemplates: state.projectTemplates,
        activeProjectTemplateId: state.activeProjectTemplateId,
      }),
    },
  ),
);
