export const spacing = [4, 8, 12, 16, 20, 24, 32, 40, 48, 64, 80] as const;

export const radius = {
  xs: 10,
  sm: 14,
  md: 18,
  lg: 24,
  xl: 28,
  hero: 32,
} as const;

export const motion = {
  hover: "120ms cubic-bezier(0.22, 1, 0.36, 1)",
  panel: "180ms cubic-bezier(0.22, 1, 0.36, 1)",
  theme: "220ms cubic-bezier(0.22, 1, 0.36, 1)",
  pulse: "240ms cubic-bezier(0.22, 1, 0.36, 1)",
  robot: "6.5s ease-in-out infinite",
} as const;

export const typography = {
  displayXl: { size: 44, line: 52, weight: 600 },
  displayLg: { size: 34, line: 42, weight: 600 },
  h1: { size: 26, line: 34, weight: 600 },
  h2: { size: 20, line: 28, weight: 600 },
  h3: { size: 16, line: 24, weight: 600 },
  bodyLg: { size: 15, line: 24, weight: 400 },
  bodyMd: { size: 14, line: 22, weight: 400 },
  label: { size: 12, line: 18, weight: 500 },
  meta: { size: 11, line: 16, weight: 500 },
  monoSm: { size: 12, line: 18, weight: 500 },
} as const;

export type ThemeMode = "light" | "dark" | "system";

