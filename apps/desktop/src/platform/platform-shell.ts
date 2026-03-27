import { sidecarBridge } from "@/services/desktop/sidecar";

export const platformShell = {
  openArtifact(path: string) {
    return sidecarBridge.openArtifact(path);
  },
  revealInFolder(path: string) {
    return sidecarBridge.revealInFolder(path);
  },
};

