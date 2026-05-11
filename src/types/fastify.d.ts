import type { FastifyReply, FastifyRequest } from "fastify";
import type { PostgresJsDatabase } from "drizzle-orm/postgres-js";
import type * as schema from "../db/schema.js";
import type { AppEnv } from "../config/env.js";
import type { EventBus } from "../modules/realtime/event-bus.js";
import type { RealtimeHub } from "../modules/realtime/hub.js";
import type { AuthTokenPayload } from "./auth.js";

declare module "fastify" {
  interface FastifyInstance {
    config: AppEnv;
    db: PostgresJsDatabase<typeof schema>;
    services: {
      eventBus: EventBus;
      realtimeHub: RealtimeHub;
    };
    authenticateUser: (request: FastifyRequest, reply: FastifyReply) => Promise<void>;
    authenticateRuntime: (request: FastifyRequest, reply: FastifyReply) => Promise<void>;
  }

  interface FastifyRequest {
    auth?: AuthTokenPayload;
  }
}

export {};
