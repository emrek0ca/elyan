import React from "react";
import {palette} from "../lib/palette";

type GlassCardProps = {
  width: number;
  height: number;
  x: number;
  y: number;
  children: React.ReactNode;
  padding?: number;
  radius?: number;
};

export const GlassCard: React.FC<GlassCardProps> = ({
  width,
  height,
  x,
  y,
  children,
  padding = 32,
  radius = 36,
}) => {
  return (
    <div
      style={{
        position: "absolute",
        left: x,
        top: y,
        width,
        height,
        borderRadius: radius,
        border: `1px solid rgba(34, 65, 76, 0.12)`,
        background: `linear-gradient(180deg, ${palette.glassStrong} 0%, ${palette.glass} 100%)`,
        boxShadow: "0 40px 80px rgba(10, 20, 24, 0.08), inset 0 1px 0 rgba(255,255,255,0.72)",
        padding,
        backdropFilter: "blur(24px)",
      }}
    >
      {children}
    </div>
  );
};
