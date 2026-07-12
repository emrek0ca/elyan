import type { FastifyReply, FastifyRequest } from "fastify";
import type { PostgresJsDatabase } from "drizzle-orm/postgres-js";
import type * as schema from "../db/schema.js";
import type { AppEnv } from "../config/env.js";
import type { EventBus } from "../modules/realtime/event-bus.js";
import type { RealtimeHub } from "../modules/realtime/hub.js";
import type { ReliabilityServices } from "../lib/reliability/index.js";
import type { BlobService } from "../lib/blob/blob-service.js";
import type { AuthTokenPayload } from "./auth.js";

declare module "fastify" {
  interface FastifyInstance {
    config: AppEnv;
    db: PostgresJsDatabase<typeof schema>;
    services: {
      eventBus: EventBus;
      realtimeHub: RealtimeHub;
      reliability: ReliabilityServices;
      blobs: BlobService;
    };
    authenticateUser: (request: FastifyRequest, reply: FastifyReply) => Promise<void>;
    authenticateRuntime: (request: FastifyRequest, reply: FastifyReply) => Promise<void>;
    authenticateUserOrRuntime: (request: FastifyRequest, reply: FastifyReply) => Promise<void>;
  }

  interface FastifyRequest {
    auth?: AuthTokenPayload;
  }
}

export {};
