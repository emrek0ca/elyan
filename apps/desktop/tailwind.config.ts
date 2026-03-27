import type { Config } from "tailwindcss";

const config: Config = {
  darkMode: ["class", '[data-theme="dark"]'],
  content: ["./index.html", "./src/**/*.{ts,tsx}"],
  theme: {
    extend: {
      fontFamily: {
        display: ['"SF Pro Display"', "Geist", "Inter", "sans-serif"],
        body: ['"SF Pro Text"', "Geist", "Inter", "sans-serif"],
        mono: ['"SF Mono"', '"JetBrains Mono"', "Menlo", "monospace"],
      },
      boxShadow: {
        panel: "var(--shadow-panel)",
        elevated: "var(--shadow-elevated)",
        hero: "var(--shadow-hero)",
      },
      colors: {
        canvas: "var(--bg-canvas)",
        shell: "var(--bg-shell)",
        surface: "var(--bg-surface)",
        "surface-alt": "var(--bg-surface-alt)",
        "surface-raised": "var(--bg-surface-raised)",
        "text-primary": "var(--text-primary)",
        "text-secondary": "var(--text-secondary)",
        "text-tertiary": "var(--text-tertiary)",
        "border-subtle": "var(--border-subtle)",
        "border-strong": "var(--border-strong)",
        accent: "var(--accent-primary)",
      },
      borderRadius: {
        sm: "14px",
        md: "18px",
        lg: "24px",
        xl: "28px",
        hero: "32px",
      },
      transitionTimingFunction: {
        premium: "cubic-bezier(0.22, 1, 0.36, 1)",
      },
    },
  },
  plugins: [],
};

export default config;
