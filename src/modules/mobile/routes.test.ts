import assert from "node:assert/strict";
import test from "node:test";
import Fastify, { type FastifyRequest } from "fastify";
import { mobileRoutes } from "./routes.js";

function decorateAuthenticatedUser(app: ReturnType<typeof Fastify>) {
  app.decorateRequest("auth", null as never);
  app.decorate("authenticateUser", async (request: FastifyRequest) => {
    (request as typeof request & { auth: unknown }).auth = {
      kind: "user",
      sub: "user-1",
      sessionId: "auth-session-1",
    } as never;
  });
}

test("mobile world-signals route rejects mismatched body userId", async () => {
  const app = Fastify();
  decorateAuthenticatedUser(app);
  app.decorate("config", {
    REQUEST_BUDGET_WINDOW_MS: 60_000,
  } as never);
  app.decorate("services", {
    reliability: {
      store: {
        async increment() {
          return 1;
        },
      },
    },
  } as never);

  await app.register(mobileRoutes, { prefix: "/v1/mobile" });

  const response = await app.inject({
    method: "POST",
    url: "/v1/mobile/world-signals",
    payload: {
      schemaVersion: 1,
      clientRequestId: "req_1",
      userId: "user-2",
      deviceId: "device-ext",
      signals: [
        {
          signalId: "sig_1",
          source: "mobile",
          kind: "device",
          summary: "Device summary",
          confidence: 0.7,
          facts: { batteryBand: "normal" },
          privacy: { rawDataUploaded: false },
          createdAt: "2030-01-01T00:00:00.000Z",
        },
      ],
    },
  });

  assert.equal(response.statusCode, 403);
  assert.match(response.body, /user_mismatch/i);
  await app.close();
});

test("mobile approval mode is backend-owned and changes during the same session", async () => {
  const app = Fastify();
  decorateAuthenticatedUser(app);
  let approvalMode = "read_only_auto";
  const auditPayloads: Array<Record<string, unknown>> = [];
  let failAudit = false;

  const approvalDbOperations = {
    select() {
      return {
        from() {
          return {
            where() {
              return {
                async limit() {
                  return [{ approvalMode }];
                },
              };
            },
          };
        },
      };
    },
    update() {
      return {
        set(values: { approvalMode?: string }) {
          if (values.approvalMode) approvalMode = values.approvalMode;
          return {
            where() {
              return {
                async returning() {
                  return [{ approvalMode }];
                },
              };
            },
          };
        },
      };
    },
    insert() {
      return {
        async values(values: Record<string, unknown>) {
          if (failAudit) throw new Error("audit unavailable");
          auditPayloads.push(values);
        },
      };
    },
  };
  const approvalDb = {
    ...approvalDbOperations,
    async transaction<T>(work: (tx: typeof approvalDbOperations) => Promise<T>) {
      const previousMode = approvalMode;
      const previousAuditCount = auditPayloads.length;
      try {
        return await work(approvalDbOperations);
      } catch (error) {
        approvalMode = previousMode;
        auditPayloads.length = previousAuditCount;
        throw error;
      }
    },
  };
  app.decorate("db", approvalDb as never);

  await app.register(mobileRoutes, { prefix: "/v1/mobile" });

  const initial = await app.inject({
    method: "GET",
    url: "/v1/mobile/approval-mode",
  });
  assert.equal(initial.statusCode, 200);
  assert.equal(initial.json().mode, "read_only_auto");

  const changed = await app.inject({
    method: "PATCH",
    url: "/v1/mobile/approval-mode",
    payload: { mode: "trusted_idempotent_writes" },
  });
  assert.equal(changed.statusCode, 200);
  assert.equal(changed.json().mode, "trusted_idempotent_writes");
  assert.deepEqual(changed.json().immutableApprovalClasses, [
    "side_effect",
    "non_idempotent",
  ]);

  const refreshed = await app.inject({
    method: "GET",
    url: "/v1/mobile/approval-mode",
  });
  assert.equal(refreshed.json().mode, "trusted_idempotent_writes");
  assert.equal(auditPayloads.length, 1);

  failAudit = true;
  const rejected = await app.inject({
    method: "PATCH",
    url: "/v1/mobile/approval-mode",
    payload: { mode: "always_ask" },
  });
  assert.equal(rejected.statusCode, 500);

  const unchanged = await app.inject({
    method: "GET",
    url: "/v1/mobile/approval-mode",
  });
  assert.equal(unchanged.json().mode, "trusted_idempotent_writes");
  assert.equal(auditPayloads.length, 1);
  await app.close();
});
