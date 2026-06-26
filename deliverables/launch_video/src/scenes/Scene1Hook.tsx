import React from "react";
import {DepthBackground} from "../components/DepthBackground";
import {LogoReveal} from "../components/LogoReveal";
import {MotionTitle} from "../components/MotionTitle";
import {ParallaxLayer} from "../components/ParallaxLayer";
import {LaunchVideoProps} from "../lib/assets";

export const Scene1Hook: React.FC<Pick<LaunchVideoProps, "logoSrc">> = ({logoSrc}) => {
  return (
    <>
      <DepthBackground mode="dark" accent={false} />
      <ParallaxLayer depth={0.1}>
        <div
          style={{
            position: "absolute",
            inset: 0,
            background: "linear-gradient(180deg, rgba(255,255,255,0) 0%, rgba(255,255,255,0.04) 100%)",
          }}
        />
      </ParallaxLayer>
      <LogoReveal src={logoSrc} centerY={740} size={430} />
      <MotionTitle text="Your system now thinks." y={1240} size={86} color="#eef9fa" />
    </>
  );
};
