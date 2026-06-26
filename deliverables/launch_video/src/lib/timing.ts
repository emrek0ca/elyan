export const VIDEO_FPS = 60;
export const VIDEO_WIDTH = 1080;
export const VIDEO_HEIGHT = 1920;
export const VIDEO_DURATION = 1800;

export type SceneSpec = {
  id:
    | "scene-1-hook"
    | "scene-2-observe"
    | "scene-3-execute"
    | "scene-4-desktop"
    | "scene-5-learn"
    | "scene-6-converge"
    | "scene-7-outro";
  from: number;
  duration: number;
  transitionIn: "fade" | "iris" | "wipe-up" | "light";
  transitionOut: "fade" | "iris" | "wipe-up" | "light";
};

export const sceneSpecs: SceneSpec[] = [
  {id: "scene-1-hook", from: 0, duration: 180, transitionIn: "fade", transitionOut: "iris"},
  {id: "scene-2-observe", from: 180, duration: 300, transitionIn: "iris", transitionOut: "wipe-up"},
  {id: "scene-3-execute", from: 480, duration: 300, transitionIn: "wipe-up", transitionOut: "light"},
  {id: "scene-4-desktop", from: 780, duration: 300, transitionIn: "light", transitionOut: "fade"},
  {id: "scene-5-learn", from: 1080, duration: 300, transitionIn: "fade", transitionOut: "light"},
  {id: "scene-6-converge", from: 1380, duration: 240, transitionIn: "light", transitionOut: "wipe-up"},
  {id: "scene-7-outro", from: 1620, duration: 180, transitionIn: "wipe-up", transitionOut: "fade"},
];
