import React from "react";
import {AbsoluteFill} from "remotion";
import {gradients, palette} from "../lib/palette";
import {ParallaxLayer} from "./ParallaxLayer";

type DepthBackgroundProps = {
  mode: "dark" | "light" | "teal";
  accent?: boolean;
};

export const DepthBackground: React.FC<DepthBackgroundProps> = ({mode, accent = true}) => {
  const background =
    !accent
      ? mode === "dark"
        ? "radial-gradient(circle at 50% 42%, rgba(255,255,255,0.14) 0%, rgba(255,255,255,0.06) 16%, rgba(10,20,24,0.96) 58%, #020405 100%)"
        : "radial-gradient(circle at 50% 18%, rgba(255,255,255,0.88) 0%, #f7faf9 40%, #dfe6e5 100%)"
      : mode === "dark"
        ? gradients.hero
        : mode === "teal"
          ? `linear-gradient(180deg, #eef7f7 0%, #dce9e9 100%)`
          : gradients.softLight;

  return (
    <AbsoluteFill style={{background, overflow: "hidden"}}>
      <ParallaxLayer depth={0.18}>
        <div
          style={{
            position: "absolute",
            width: 900,
            height: 900,
            borderRadius: 999,
            background: accent ? gradients.halo : "radial-gradient(circle, rgba(255,255,255,0.34) 0%, rgba(255,255,255,0.08) 48%, rgba(255,255,255,0) 78%)",
            top: mode === "dark" ? 190 : 120,
            left: 100,
            opacity: accent ? (mode === "dark" ? 0.95 : 0.65) : mode === "dark" ? 0.42 : 0.24,
          }}
        />
      </ParallaxLayer>
      <ParallaxLayer depth={0.34} y={80}>
        <div
          style={{
            position: "absolute",
            inset: 60,
            borderRadius: 72,
            border: `1px solid ${palette.line}`,
            opacity: 0.5,
          }}
        />
      </ParallaxLayer>
      <ParallaxLayer depth={0.5} x={120} y={120} blur={mode === "dark" ? 0 : 8}>
        <div
          style={{
            position: "absolute",
            right: -160,
            top: 260,
            width: 720,
            height: 720,
            borderRadius: 999,
            background: accent
              ? "radial-gradient(circle, rgba(110,184,196,0.2) 0%, rgba(110,184,196,0.02) 60%, rgba(110,184,196,0) 80%)"
              : "radial-gradient(circle, rgba(255,255,255,0.12) 0%, rgba(255,255,255,0.03) 58%, rgba(255,255,255,0) 82%)",
            opacity: accent ? 1 : 0.55,
          }}
        />
      </ParallaxLayer>
    </AbsoluteFill>
  );
};
