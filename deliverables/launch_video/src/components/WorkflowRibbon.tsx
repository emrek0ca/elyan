import React from "react";
import {interpolate, useCurrentFrame} from "remotion";
import {palette} from "../lib/palette";

type WorkflowRibbonProps = {
  y: number;
  width?: number;
  label: string;
  accent?: string;
};

export const WorkflowRibbon: React.FC<WorkflowRibbonProps> = ({
  y,
  width = 760,
  label,
  accent = palette.teal,
}) => {
  const frame = useCurrentFrame();
  const progress = interpolate(frame, [0, 120, 220], [0, 0.45, 1], {extrapolateRight: "clamp"});
  return (
    <div
      style={{
        position: "absolute",
        left: 160,
        top: y,
        width,
        height: 88,
        borderRadius: 999,
        background: "rgba(255,255,255,0.48)",
        border: `1px solid ${palette.line}`,
        overflow: "hidden",
      }}
    >
      <div
        style={{
          position: "absolute",
          inset: 10,
          borderRadius: 999,
          background: "rgba(248,251,251,0.76)",
        }}
      />
      <div
        style={{
          position: "absolute",
          left: 10,
          top: 10,
          bottom: 10,
          width: (width - 20) * progress,
          borderRadius: 999,
          background: `linear-gradient(90deg, rgba(110,184,196,0.25) 0%, ${accent} 100%)`,
          boxShadow: `0 0 28px rgba(110,184,196,0.28)`,
        }}
      />
      <div
        style={{
          position: "absolute",
          left: 40,
          top: 24,
          fontFamily: '-apple-system, BlinkMacSystemFont, "SF Pro Display", sans-serif',
          fontSize: 28,
          color: palette.shadow,
          letterSpacing: -0.4,
        }}
      >
        {label}
      </div>
    </div>
  );
};
