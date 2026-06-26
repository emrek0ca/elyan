export const palette = {
  ink: "#071015",
  shadow: "#0f1d25",
  teal: "#6eb8c4",
  tealBright: "#b9edf1",
  tealDeep: "#295867",
  mist: "#e8efef",
  fog: "#d6e0df",
  cloud: "#f7faf9",
  line: "rgba(34, 65, 76, 0.12)",
  glass: "rgba(255,255,255,0.52)",
  glassStrong: "rgba(255,255,255,0.78)",
  glow: "rgba(144, 217, 223, 0.42)",
} as const;

export const gradients = {
  hero: `radial-gradient(circle at 50% 42%, ${palette.tealBright} 0%, rgba(185, 237, 241, 0.44) 16%, rgba(10, 20, 24, 0.96) 58%, #020405 100%)`,
  softLight: `radial-gradient(circle at 50% 18%, rgba(214, 242, 244, 0.9) 0%, ${palette.cloud} 38%, ${palette.fog} 100%)`,
  halo: `radial-gradient(circle, rgba(185, 237, 241, 0.9) 0%, rgba(138, 201, 208, 0.45) 30%, rgba(110, 184, 196, 0.08) 58%, rgba(110, 184, 196, 0) 74%)`,
} as const;
