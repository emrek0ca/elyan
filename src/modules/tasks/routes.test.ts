import assert from "node:assert/strict";
import test from "node:test";
import Fastify from "fastify";
import { errorHandlerPlugin } from "../../plugins/error-handler.js";
import { taskRoutes } from "./routes.js";

class FakeQuery<T> {
  constructor(private readonly result: T) {}

  from() {
    return this;
  }

  where() {
    return this;
  }

  orderBy() {
    return this;
  }

  limit() {
    return this;
  }

  then<TResult1 = T, TResult2 = never>(
    resolve?: ((value: T) => TResult1 | PromiseLike<TResult1>) | null,
    reject?: ((reason: unknown) => TResult2 | PromiseLike<TResult2>) | null,
  ) {
    return Promise.resolve(this.result).then(resolve, reject);
  }
}

class SequenceDb {
  constructor(private readonly selects: unknown[]) {}

  select() {
    return new FakeQuery(this.selects.shift() ?? []);
  }
}

test("task detail rejects tasks owned by another user", async () => {
  const app = Fastify();
  app.decorate("authenticateUser", async (request) => {
    (request as typeof request & { auth: unknown }).auth = {
      kind: "user",
      sub: "user-1",
      sessionId: "session-1",
      email: "user@example.com",
    };
  });
  app.decorate("db", new SequenceDb([[], []]) as never);
  await app.register(errorHandlerPlugin);
  await app.register(taskRoutes, { prefix: "/v1/tasks" });

  const response = await app.inject({
    method: "GET",
    url: "/v1/tasks/00000000-0000-4000-8000-000000000001",
  });

  assert.equal(response.statusCode, 404);
  await app.close();
});
