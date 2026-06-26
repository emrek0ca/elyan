import React from "react";
import {DepthBackground} from "../components/DepthBackground";
import {HeroOutro} from "../components/HeroOutro";
import {LaunchVideoProps} from "../lib/assets";

export const Scene7Outro: React.FC<Pick<LaunchVideoProps, "logoSrc">> = ({logoSrc}) => {
  return (
    <>
      <DepthBackground mode="light" accent={false} />
      <HeroOutro logoSrc={logoSrc} />
    </>
  );
};
