export const lightTheme = {
  bg: {
    canvas: "#F7F3EA",
    shell: "#FBF8F1",
    surface: "#FFFFFF",
    surfaceAlt: "#F8F4EC",
    surfaceRaised: "#FFFDF8",
    overlay: "rgba(247,243,234,0.76)",
  },
  text: {
    primary: "#16181D",
    secondary: "#60646F",
    tertiary: "#969083",
    inverse: "#FBF8F1",
  },
  border: {
    subtle: "#E5DCCF",
    strong: "#D6CAB9",
    focus: "#B8C4FF",
  },
  accent: {
    primary: "#3654D6",
    soft: "rgba(54,84,214,0.08)",
    glow: "rgba(54,84,214,0.12)",
    contrast: "#FFFFFF",
  },
  state: {
    success: "#169B5C",
    warning: "#D48A17",
    error: "#D94A43",
    info: "#4E7BFF",
  },
  shadow: {
    panel: "0 8px 22px rgba(36,31,24,0.045)",
    elevated: "0 16px 40px rgba(36,31,24,0.06)",
    hero: "0 24px 64px rgba(36,31,24,0.08)",
  },
} as const;
