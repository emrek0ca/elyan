import React from "react";
import {interpolate, useCurrentFrame} from "remotion";
import type {SceneSpec} from "../lib/timing";

type CinematicTransitionProps = {
  scene: SceneSpec;
};

export const CinematicTransition: React.FC<CinematicTransitionProps> = ({scene}) => {
  const frame = useCurrentFrame();
  const local = frame - scene.from;
  if (local < 0 || local > scene.duration) {
    return null;
  }
  const inProgress = interpolate(local, [0, 24], [1, 0], {extrapolateRight: "clamp"});
  const outProgress = interpolate(local, [scene.duration - 24, scene.duration], [0, 1], {extrapolateLeft: "clamp"});
  const opacity = Math.max(inProgress, outProgress);
  const translate = interpolate(local, [scene.duration - 24, scene.duration], [0, -120], {
    extrapolateLeft: "clamp",
  });
  const background =
    scene.transitionOut === "light"
      ? "linear-gradient(180deg, rgba(243,249,249,0.0) 0%, rgba(243,249,249,0.88) 100%)"
      : "linear-gradient(180deg, rgba(4,8,10,0.0) 0%, rgba(4,8,10,0.92) 100%)";
  return (
    <div
      style={{
        position: "absolute",
        inset: 0,
        opacity,
        pointerEvents: "none",
        background,
        transform: scene.transitionOut === "wipe-up" ? `translateY(${translate}px)` : undefined,
        mixBlendMode: scene.transitionOut === "light" ? "screen" : "normal",
      }}
    />
  );
};
