import type { FastifyInstance } from "fastify";
import { addMilliseconds, parseDurationToMs } from "./time.js";
import type { RuntimeAuthTokenPayload, UserAuthTokenPayload } from "../types/auth.js";

export async function signUserAccessToken(app: FastifyInstance, payload: UserAuthTokenPayload): Promise<string> {
  return app.jwt.sign(payload, { expiresIn: app.config.ACCESS_TOKEN_TTL });
}

export async function signUserRefreshToken(app: FastifyInstance, payload: UserAuthTokenPayload): Promise<string> {
  return app.jwt.sign(payload, { expiresIn: app.config.REFRESH_TOKEN_TTL });
}

export async function signRuntimeAccessToken(
  app: FastifyInstance,
  payload: RuntimeAuthTokenPayload,
): Promise<string> {
  return app.jwt.sign(payload, { expiresIn: app.config.RUNTIME_TOKEN_TTL });
}

export function calculateRefreshTokenExpiry(ttl: string): Date {
  return addMilliseconds(new Date(), parseDurationToMs(ttl));
}
