import type { DeviceType } from "../contracts/domain.js";

export type UserAuthTokenPayload = {
  kind: "user";
  sub: string;
  sessionId: string;
  email: string;
};

export type RuntimeAuthTokenPayload = {
  kind: "runtime";
  sub: string;
  deviceId: string;
  deviceType: DeviceType;
  connectionId: string;
};

export type AuthTokenPayload = UserAuthTokenPayload | RuntimeAuthTokenPayload;
