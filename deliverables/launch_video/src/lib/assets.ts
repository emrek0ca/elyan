import {staticFile} from "remotion";

export type LaunchVideoProps = {
  logoSrc: string;
  scene2RobotSrc: string;
  scene5RobotSrc: string;
  mutedSafe?: boolean;
};

export type AssetManifest = {
  logo: string;
  robots: {
    scene2: string;
    scene5: string;
  };
  sfx: {
    start: string;
    think: string;
    hud: string;
    done: string;
  };
};

export const assetManifest: AssetManifest = {
  logo: staticFile("assets/brand/logo.png"),
  robots: {
    scene2: staticFile("assets/robots/scene-2-robot.png"),
    scene5: staticFile("assets/robots/scene-5-robot.png"),
  },
  sfx: {
    start: staticFile("assets/sfx/start.mp3"),
    think: staticFile("assets/sfx/think.mp3"),
    hud: staticFile("assets/sfx/hud.mp3"),
    done: staticFile("assets/sfx/done.mp3"),
  },
};

export const defaultLaunchVideoProps: LaunchVideoProps = {
  logoSrc: assetManifest.logo,
  scene2RobotSrc: assetManifest.robots.scene2,
  scene5RobotSrc: assetManifest.robots.scene5,
  mutedSafe: true,
};
