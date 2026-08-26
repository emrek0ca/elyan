import assert from "node:assert/strict";
import test from "node:test";
import { mcpPermissionCacheKey } from "./mcp-tools.js";

test("MCP permission cache keys are scoped to the connection and server", () => {
  const declaration = {
    appId: "notion",
    remoteToolName: "search",
    connectionId: "connection-a",
    serverId: "server-a",
    serverUrl: "https://mcp.example.test/a",
  };

  assert.equal(mcpPermissionCacheKey(declaration), mcpPermissionCacheKey({ ...declaration }));
  assert.notEqual(
    mcpPermissionCacheKey(declaration),
    mcpPermissionCacheKey({ ...declaration, connectionId: "connection-b" }),
  );
  assert.notEqual(
    mcpPermissionCacheKey(declaration),
    mcpPermissionCacheKey({ ...declaration, serverId: "server-b" }),
  );
  assert.notEqual(
    mcpPermissionCacheKey(declaration),
    mcpPermissionCacheKey({ ...declaration, serverUrl: "https://mcp.example.test/b" }),
  );
});

test("an in-flight connected-tool call can be cancelled, not just refused before it starts", async () => {
  // `shouldAbort` kancası `AgentToolContext` içinde ZATEN vardı ve MCP
  // çağrısından ÖNCE soruluyordu — ama çağrı başladıktan sonra bir daha
  // sorulmuyordu. Kullanıcı görevi iptal ettiğinde yirmi saniyelik HTTP
  // isteği sonuna kadar çalışıyor, iptal ancak o bittikten sonra fark
  // ediliyordu.
  //
  // Burada sinyalin GERÇEKTEN uçuşta tetiklendiği doğrulanır: `shouldAbort`
  // ilk yoklamadan sonra true döner ve isteğin kendisi kesilir.
  const { abortSignalFrom } = (await import(
    "./mcp-tools.js"
  )) as unknown as {
    abortSignalFrom: (
      shouldAbort: (() => boolean | Promise<boolean>) | undefined,
    ) => { signal?: AbortSignal; dispose: () => void };
  };

  // Kanca verilmezse sinyal de üretilmez: mevcut davranış aynen korunur.
  const none = abortSignalFrom(undefined);
  assert.equal(none.signal, undefined);
  none.dispose();

  let asked = 0;
  const abort = abortSignalFrom(() => {
    asked += 1;
    return asked > 1;
  });
  assert.ok(abort.signal, "kanca verildiğinde sinyal üretilmeli");
  assert.equal(abort.signal?.aborted, false);

  await new Promise((resolve) => setTimeout(resolve, 900));
  assert.ok(asked >= 2, `yoklama çalışmalı (sorulan: ${asked})`);
  assert.equal(abort.signal?.aborted, true, "iptal uçuşta tetiklenmeli");

  // Zamanlayıcı sızmamalı.
  const askedAtDispose = asked;
  abort.dispose();
  await new Promise((resolve) => setTimeout(resolve, 600));
  assert.equal(asked, askedAtDispose, "dispose sonrası yoklama durmalı");
});
