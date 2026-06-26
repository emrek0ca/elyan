import "./index.css";
import {Composition} from "remotion";
import {ElyanLaunchVertical} from "./compositions/ElyanLaunchVertical";
import {defaultLaunchVideoProps} from "./lib/assets";
import {VIDEO_DURATION, VIDEO_FPS, VIDEO_HEIGHT, VIDEO_WIDTH} from "./lib/timing";

export const RemotionRoot: React.FC = () => {
  return (
    <>
      <Composition
        id="ElyanLaunchVertical"
        component={ElyanLaunchVertical}
        durationInFrames={VIDEO_DURATION}
        fps={VIDEO_FPS}
        width={VIDEO_WIDTH}
        height={VIDEO_HEIGHT}
        defaultProps={defaultLaunchVideoProps}
      />
    </>
  );
};
