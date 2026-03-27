export const lightTheme = {
  bg: {
    canvas: "#F6F7F9",
    shell: "#FBFCFE",
    surface: "#FFFFFF",
    surfaceAlt: "#F9FAFC",
    surfaceRaised: "#FCFDFE",
    overlay: "rgba(246,247,249,0.78)",
  },
  text: {
    primary: "#0F141C",
    secondary: "#596273",
    tertiary: "#8A95A8",
    inverse: "#F6F7F9",
  },
  border: {
    subtle: "#E7EBF1",
    strong: "#D9E1EC",
    focus: "#C7D4FF",
  },
  accent: {
    primary: "#5B7CFF",
    soft: "#ECF1FF",
    glow: "rgba(91,124,255,0.16)",
    contrast: "#FFFFFF",
  },
  state: {
    success: "#169B5C",
    warning: "#D48A17",
    error: "#D94A43",
    info: "#4E7BFF",
  },
  shadow: {
    panel: "0 10px 30px rgba(16,24,40,0.05)",
    elevated: "0 24px 60px rgba(16,24,40,0.07)",
    hero: "0 28px 64px rgba(16,24,40,0.10)",
  },
} as const;

