"use client";

import React, { createContext, useContext, useEffect, useState } from 'react';

export type ThemeMode = 'light' | 'dark' | 'system';
export type TextScale = 'small' | 'standard' | 'large';
export type InterfaceDensity = 'compact' | 'standard' | 'comfortable';

interface PreferencesState {
  themeMode: ThemeMode;
  themeModeExplicit: boolean;
  textScale: TextScale;
  interfaceDensity: InterfaceDensity;
  chatRetention: string;
}

interface PreferencesContextType extends PreferencesState {
  updatePreference: <K extends keyof PreferencesState>(key: K, value: PreferencesState[K]) => void;
}

const defaultPreferences: PreferencesState = {
  themeMode: 'light',
  themeModeExplicit: false,
  textScale: 'standard',
  interfaceDensity: 'standard',
  chatRetention: '30', // days, or 'forever'
};

const PreferencesContext = createContext<PreferencesContextType | undefined>(undefined);

export function PreferencesProvider({ children }: { children: React.ReactNode }) {
  const [preferences, setPreferences] = useState<PreferencesState>(defaultPreferences);
  const [mounted, setMounted] = useState(false);

  // Load from localStorage on mount
  useEffect(() => {
    try {
      const stored = localStorage.getItem('elyan_web_preferences');
      if (stored) {
        const parsed = JSON.parse(stored);
        const migratedPreferences = { ...defaultPreferences, ...parsed };
        if (parsed.themeMode === 'system' && parsed.themeModeExplicit !== true) {
          migratedPreferences.themeMode = 'light';
        }
        setPreferences(migratedPreferences);
      }
    } catch (e) {
      console.error('Failed to load preferences', e);
    }
    setMounted(true);
  }, []);

  // Save to localStorage when changed
  useEffect(() => {
    if (!mounted) return;
    try {
      localStorage.setItem('elyan_web_preferences', JSON.stringify(preferences));
    } catch (e) {
      console.error('Failed to save preferences', e);
    }
  }, [preferences, mounted]);

  // Apply classes to document element based on preferences
  useEffect(() => {
    if (!mounted) return;

    const root = document.documentElement;
    const systemTheme = window.matchMedia('(prefers-color-scheme: dark)');
    const applyTheme = () => {
      root.classList.remove('theme-light', 'theme-dark');
      const resolvedTheme =
        preferences.themeMode === 'system'
          ? systemTheme.matches ? 'dark' : 'light'
          : preferences.themeMode;
      root.classList.add(`theme-${resolvedTheme}`);
    };

    applyTheme();
    if (preferences.themeMode === 'system') {
      systemTheme.addEventListener('change', applyTheme);
    }

    // Text Scale
    root.classList.remove('text-small', 'text-standard', 'text-large');
    root.classList.add(`text-${preferences.textScale}`);

    // Density
    root.classList.remove('density-compact', 'density-standard', 'density-comfortable');
    root.classList.add(`density-${preferences.interfaceDensity}`);

    return () => {
      systemTheme.removeEventListener('change', applyTheme);
    };
  }, [preferences, mounted]);

  const updatePreference = <K extends keyof PreferencesState>(key: K, value: PreferencesState[K]) => {
    setPreferences(prev => ({
      ...prev,
      [key]: value,
      ...(key === 'themeMode' ? { themeModeExplicit: true } : {})
    }));
  };

  return (
    <PreferencesContext.Provider value={{ ...preferences, updatePreference }}>
      {children}
    </PreferencesContext.Provider>
  );
}

export function usePreferences() {
  const context = useContext(PreferencesContext);
  if (context === undefined) {
    throw new Error('usePreferences must be used within a PreferencesProvider');
  }
  return context;
}
