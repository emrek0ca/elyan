import assert from "node:assert/strict";
import test from "node:test";
import { deleteAiProviderCredential, listAiProviderCredentials, listAiProviderRegistryForUser, upsertAiProviderCredential } from "./service.js";

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

  then<TResult1 = T, TResult2 = never>(
    resolve?: ((value: T) => TResult1 | PromiseLike<TResult1>) | null,
    reject?: ((reason: unknown) => TResult2 | PromiseLike<TResult2>) | null,
  ) {
    return Promise.resolve(this.result).then(resolve, reject);
  }
}

class FakeDb {
  constructor(private readonly rows: unknown[] = []) {}

  select() {
    return new FakeQuery(this.rows);
  }

  insert() {
    throw new Error("unexpected insert");
  }

  update() {
    throw new Error("unexpected update");
  }

  delete() {
    throw new Error("unexpected delete");
  }
}

test("listAiProviderRegistryForUser exposes Groq only", async () => {
  const app = {
    db: new FakeDb([]),
    config: {},
  };

  const providers = await listAiProviderRegistryForUser(app as never, "user-1");

  assert.deepEqual(
    providers.map((provider) => provider.code),
    ["groq"],
  );
  assert.deepEqual(providers[0]?.models, ["openai/gpt-oss-120b", "openai/gpt-oss-20b", "qwen/qwen3.6-27b"]);
  assert.equal(providers[0]?.defaultModel, "openai/gpt-oss-120b");
});

test("upsertAiProviderCredential rejects non-groq providers", async () => {
  const app = {
    db: new FakeDb([]),
    config: {},
  };

  await assert.rejects(
    () =>
      upsertAiProviderCredential(app as never, {
        userId: "user-1",
        provider: "openai" as never,
        baseUrl: "http://127.0.0.1:11434",
      }),
    (error) => {
      assert.equal(error instanceof Error, true);
      assert.equal((error as Error).message, "Only Groq is supported on the server control plane");
      return true;
    },
  );
});

test("listAiProviderCredentials keeps only Groq rows", async () => {
  const app = {
    db: new FakeDb([
      {
        id: "cred-1",
        provider: "openai",
        label: "Local",
        defaultModel: "llama3.2",
        baseUrl: "http://127.0.0.1:11434",
        metadata: {},
        updatedAt: new Date("2030-01-01T00:00:00.000Z"),
      },
      {
        id: "cred-2",
        provider: "groq",
        label: "Groq",
        defaultModel: "openai/gpt-oss-20b",
        baseUrl: "https://api.groq.com/openai/v1",
        metadata: {},
        updatedAt: new Date("2030-01-02T00:00:00.000Z"),
      },
    ]),
    config: {},
  };

  const credentials = await listAiProviderCredentials(app as never, "user-1");

  assert.equal(credentials.length, 1);
  assert.equal(credentials[0]?.provider, "groq");
});

test("deleteAiProviderCredential rejects non-groq providers", async () => {
  const app = {
    db: new FakeDb([]),
    config: {},
  };

  await assert.rejects(
    () =>
      deleteAiProviderCredential(app as never, {
        userId: "user-1",
        provider: "openai" as never,
      }),
    (error) => {
      assert.equal(error instanceof Error, true);
      assert.equal((error as Error).message, "Only Groq is supported on the server control plane");
      return true;
    },
  );
});
