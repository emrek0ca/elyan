import type { FastifyRequest } from "fastify";
import { unauthorized } from "./errors.js";
import { getHeaderString } from "./http.js";
import type { AuthTokenPayload, RuntimeAuthTokenPayload, UserAuthTokenPayload } from "../types/auth.js";

export function extractBearerToken(request: FastifyRequest): string {
  const header = getHeaderString(request.headers.authorization);

  if (header?.startsWith("Bearer ")) {
    return header.slice("Bearer ".length).trim();
  }

  const query = request.query as { token?: string } | undefined;

  if (query?.token) {
    return query.token;
  }

  throw unauthorized("Bearer token is required");
}

export function getAuthPayload(request: FastifyRequest): AuthTokenPayload {
  if (!request.auth) {
    throw unauthorized();
  }

  return request.auth;
}

export function getUserAuth(request: FastifyRequest): UserAuthTokenPayload {
  const auth = getAuthPayload(request);

  if (auth.kind !== "user") {
    throw unauthorized("User token required");
  }

  return auth;
}

export function getUserScopedAuth(request: FastifyRequest): { sub: string; kind: "user" | "runtime" } {
  // Kullanıcı VEYA runtime token'ı — runtime token'ın sub'ı cihaz sahibinin
  // userId'sidir (claim anında bağlanır), bu yüzden kullanıcı-kapsamlı
  // kaynaklara (chat, brain) eşleşmiş masaüstü de erişebilir.
  const auth = getAuthPayload(request);

  if (auth.kind !== "user" && auth.kind !== "runtime") {
    throw unauthorized("User or runtime token required");
  }

  if (!auth.sub) {
    throw unauthorized("Token is not bound to a user");
  }

  return { sub: auth.sub, kind: auth.kind };
}

export function getRuntimeAuth(request: FastifyRequest): RuntimeAuthTokenPayload {
  const auth = getAuthPayload(request);

  if (auth.kind !== "runtime") {
    throw unauthorized("Runtime token required");
  }

  return auth;
}
