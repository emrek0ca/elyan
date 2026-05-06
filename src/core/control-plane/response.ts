import {
  type ControlPlaneHostedDevice,
  type ControlPlaneHostedProfile,
} from './types';

export type ControlPlaneProfileResponse = {
  session: ControlPlaneHostedProfile['session'];
  profile: ControlPlaneHostedProfile;
  account: ControlPlaneHostedProfile['account'];
};

export type ControlPlaneHostedDeviceResponse = ControlPlaneHostedDevice;

export type ControlPlanePanelResponse = ControlPlaneProfileResponse & {
  devices: ControlPlaneHostedDeviceResponse[];
};

export function serializeControlPlaneHostedDevice(device: ControlPlaneHostedDevice): ControlPlaneHostedDeviceResponse {
  return device;
}

export function buildControlPlaneProfileResponse(profile: ControlPlaneHostedProfile): ControlPlaneProfileResponse {
  return {
    session: profile.session,
    profile,
    account: profile.account,
  };
}

export function buildControlPlanePanelResponse(
  profile: ControlPlaneHostedProfile,
  devices: ControlPlaneHostedDevice[]
): ControlPlanePanelResponse {
  const base = buildControlPlaneProfileResponse(profile);

  return {
    ...base,
    devices: devices.map(serializeControlPlaneHostedDevice),
  };
}
