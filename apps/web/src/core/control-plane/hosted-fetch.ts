type HostedControlPlaneStatus = {
  surfaces: {
    hosted: {
      ready: boolean;
    };
  };
  controlPlane: {
    health?: {
      connection?: {
        hostedReady?: boolean;
      };
    };
  };
};

export function shouldFetchHostedControlPlane(status: HostedControlPlaneStatus) {
  return Boolean(
    status.surfaces.hosted.ready ||
      status.controlPlane.health?.connection?.hostedReady
  );
}
