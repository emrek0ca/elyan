export const darkTheme = {
  bg: {
    canvas: "#0D1117",
    shell: "#11161D",
    surface: "#141A22",
    surfaceAlt: "#171E27",
    surfaceRaised: "#1B2330",
    overlay: "rgba(13,17,23,0.72)",
  },
  text: {
    primary: "#F3F6FA",
    secondary: "#AAB4C3",
    tertiary: "#7E8898",
    inverse: "#0D1117",
  },
  border: {
    subtle: "#242D39",
    strong: "#313C49",
    focus: "#4E66C5",
  },
  accent: {
    primary: "#7D98FF",
    soft: "rgba(125,152,255,0.14)",
    glow: "rgba(125,152,255,0.22)",
    contrast: "#F3F6FA",
  },
  state: {
    success: "#28B26D",
    warning: "#E6A62B",
    error: "#F06A61",
    info: "#8DA8FF",
  },
  shadow: {
    panel: "0 12px 30px rgba(0,0,0,0.24)",
    elevated: "0 24px 64px rgba(0,0,0,0.28)",
    hero: "0 30px 72px rgba(0,0,0,0.34)",
  },
} as const;

