import assert from "node:assert/strict";
import { test } from "node:test";
import {
  CONNECTOR_TOOL_CONTRACTS,
  connectorToolContract,
  connectorContractsForSemanticReadHint,
  connectorToolsForCapabilities,
  connectorToolsForCapabilityGrants,
  isConnectorTool,
  selectSemanticConnectorReadToolHint,
} from "./connector-tools.js";
import {
  resetSemanticComputeWorkerForTests,
  setSemanticComputeDispatcherForTests,
} from "./semantic-compute-client.js";
import {
  connectorWriteTaskIdFromToken,
  stageConnectorWriteApproval,
} from "./connector-write-approvals.js";
import { missingOauthScopes } from "../integrations/service.js";
import { getAgentToolMetadata, listAgentTools } from "./tool-registry.js";

function semanticTestVector(
  index: number,
  secondIndex?: number,
): number[] {
  const vector = new Array<number>(384).fill(0);
  if (secondIndex === undefined) {
    vector[index] = 1;
  } else {
    const value = 1 / Math.sqrt(2);
    vector[index] = value;
    vector[secondIndex] = value;
  }
  return vector;
}

function connectorSemanticPassageVector(text: string): number[] {
  const normalized = text.toLowerCase();
  if (normalized.includes("gmail.search")) return semanticTestVector(0);
  if (normalized.includes("gmail.read")) return semanticTestVector(1);
  if (normalized.includes("explain, teach")) return semanticTestVector(2);
  if (normalized.includes("draft, rewrite")) return semanticTestVector(3);
  if (normalized.includes("create, send")) return semanticTestVector(4);
  return semanticTestVector(5);
}

function gmailReadContracts(): string[] {
  return CONNECTOR_TOOL_CONTRACTS.filter(
    (entry) => entry.capability === "gmail" && entry.permission === "read",
  ).map((entry) => entry.contract);
}

test("semantic connector selector maps an unseen Gmail paraphrase to the advertised read tool", async () => {
  resetSemanticComputeWorkerForTests();
  setSemanticComputeDispatcherForTests(async ({ texts }) =>
    texts.map((text) =>
      text.toLowerCase().startsWith("query:")
        ? semanticTestVector(0)
        : connectorSemanticPassageVector(text),
    ),
  );
  try {
    const hint = await selectSemanticConnectorReadToolHint(
      "Bugün gelen mailler",
      gmailReadContracts(),
    );
    assert.equal(hint?.tool, "gmail.search");
    assert.equal(hint?.source, "transformer");
    assert.ok((hint?.score ?? 0) >= 0.72);
    assert.ok((hint?.margin ?? 0) >= 0.04);
  } finally {
    resetSemanticComputeWorkerForTests();
  }
});

test("semantic connector selector rejects meta explanations even when Gmail is advertised", async () => {
  resetSemanticComputeWorkerForTests();
  setSemanticComputeDispatcherForTests(async ({ texts }) =>
    texts.map((text) =>
      text.toLowerCase().startsWith("query:")
        ? semanticTestVector(2)
        : connectorSemanticPassageVector(text),
    ),
  );
  try {
    assert.equal(
      await selectSemanticConnectorReadToolHint(
        "Gmail API nasıl çalışıyor, açıklar mısın?",
        gmailReadContracts(),
      ),
      null,
    );
  } finally {
    resetSemanticComputeWorkerForTests();
  }
});

test("semantic connector selector consumes typed side-effect risk before model routing", async () => {
  resetSemanticComputeWorkerForTests();
  let semanticComputeCalled = false;
  setSemanticComputeDispatcherForTests(async ({ texts }) => {
    semanticComputeCalled = true;
    return texts.map(() => semanticTestVector(0));
  });
  try {
    assert.equal(
      await selectSemanticConnectorReadToolHint(
        "Ayse'ye yarinki toplanti icin e-posta gonder",
        gmailReadContracts(),
        { sideEffectDetected: true },
      ),
      null,
    );
    assert.equal(semanticComputeCalled, false);
  } finally {
    resetSemanticComputeWorkerForTests();
  }
});

test("semantic connector selector fails closed on ambiguous and low-confidence matches", async () => {
  resetSemanticComputeWorkerForTests();
  setSemanticComputeDispatcherForTests(async ({ texts }) =>
    texts.map((text) => {
      if (!text.toLowerCase().startsWith("query:")) {
        return connectorSemanticPassageVector(text);
      }
      return text.includes("ambiguous")
        ? semanticTestVector(0, 1)
        : semanticTestVector(9);
    }),
  );
  try {
    assert.equal(
      await selectSemanticConnectorReadToolHint(
        "ambiguous account request",
        gmailReadContracts(),
      ),
      null,
    );
    assert.equal(
      await selectSemanticConnectorReadToolHint(
        "low confidence unrelated request",
        gmailReadContracts(),
      ),
      null,
    );
  } finally {
    resetSemanticComputeWorkerForTests();
  }
});

test("semantic connector contract gate advertises only the selected read tool", () => {
  const contracts = CONNECTOR_TOOL_CONTRACTS.filter(
    (entry) => entry.permission === "read",
  ).map((entry) => entry.contract);
  assert.deepEqual(
    connectorContractsForSemanticReadHint(contracts, null),
    [],
  );
  const selected = connectorContractsForSemanticReadHint(
    contracts,
    "gmail.search",
  );
  assert.equal(selected.length, 1);
  assert.match(selected[0] ?? "", /^gmail\.search\b/u);
});

test("connectorToolsForCapabilities advertises only connected capabilities", () => {
  const gmailOnly = connectorToolsForCapabilities(["gmail"]).map(
    (entry) => entry.name,
  );
  assert.deepEqual(gmailOnly.sort(), ["gmail.read", "gmail.search"]);

  const none = connectorToolsForCapabilities([]);
  assert.equal(none.length, 0);

  const all = connectorToolsForCapabilities(["gmail", "calendar", "drive"]).map(
    (entry) => entry.name,
  );
  assert.deepEqual(all.sort(), [
    "calendar.list_events",
    "drive.search",
    "gmail.read",
    "gmail.search",
  ]);
});

test("connectorToolsForCapabilityGrants advertises only tools with usable scopes", () => {
  const hasScopes = (
    provider: string,
    grantedScopes: string[],
    requiredScopes: string[],
  ) => missingOauthScopes(provider, grantedScopes, requiredScopes).length === 0;

  const gmailReadonlyOnly = connectorToolsForCapabilityGrants(
    [
      {
        provider: "google",
        capabilities: ["gmail"],
        scopes: ["https://www.googleapis.com/auth/gmail.readonly"],
      },
    ],
    hasScopes,
  ).map((entry) => entry.name);
  assert.deepEqual(gmailReadonlyOnly.sort(), ["gmail.read", "gmail.search"]);

  const calendarEventsReadonly = connectorToolsForCapabilityGrants(
    [
      {
        provider: "google",
        capabilities: ["calendar"],
        scopes: ["https://www.googleapis.com/auth/calendar.events.readonly"],
      },
    ],
    hasScopes,
  ).map((entry) => entry.name);
  assert.deepEqual(calendarEventsReadonly, ["calendar.list_events"]);

  const calendarProviderReadonly = connectorToolsForCapabilityGrants(
    [
      {
        provider: "google",
        capabilities: ["calendar"],
        scopes: ["https://www.googleapis.com/auth/calendar.readonly"],
      },
    ],
    hasScopes,
  ).map((entry) => entry.name);
  assert.deepEqual(calendarProviderReadonly, ["calendar.list_events"]);

  const missingCalendarScope = connectorToolsForCapabilityGrants(
    [{ provider: "google", capabilities: ["calendar"], scopes: ["email"] }],
    hasScopes,
  );
  assert.equal(missingCalendarScope.length, 0);
});

test("connector tool contracts each map to a registered agent tool", () => {
  const registered = new Map(
    listAgentTools().map((tool) => [tool.name, tool.permission]),
  );
  for (const entry of CONNECTOR_TOOL_CONTRACTS) {
    assert.equal(
      registered.get(entry.name),
      entry.permission,
      `${entry.name} must be registered with matching permission`,
    );
    const metadata = getAgentToolMetadata(entry.name);
    assert.ok(metadata, `${entry.name} metadata missing`);
    assert.equal(
      metadata?.idempotency,
      entry.permission === "read" ? "read_only" : "non_idempotent",
    );
    assert.equal(metadata?.parallelSafe, entry.permission === "read");
    assert.ok(isConnectorTool(entry.name));
    assert.ok(connectorToolContract(entry.name));
  }
});

test("side-effect connector tools are registered but not advertised automatically", () => {
  const advertised = connectorToolsForCapabilities([
    "gmail",
    "calendar",
    "drive",
  ]).map((entry) => entry.name);
  assert.equal(advertised.includes("gmail.send"), false);
  assert.equal(advertised.includes("calendar.create_event"), false);
  assert.equal(connectorToolContract("gmail.send")?.permission, "side_effect");
  assert.equal(
    connectorToolContract("calendar.create_event")?.permission,
    "side_effect",
  );
});

test("unknown tools are not treated as connectors", () => {
  assert.equal(isConnectorTool("web.search"), false);
  assert.equal(connectorToolContract("web.search"), null);
});

test("connector writes stage a durable task-bound approval without process state", () => {
  const taskId = "11111111-1111-4111-8111-111111111111";
  const staged = stageConnectorWriteApproval({
    userId: "user-1",
    taskId,
    sessionId: "session-1",
    workload: "mobile_chat_balanced",
    request: {
      tool: "gmail.send",
      args: {
        to: "user@example.com",
        subject: "Test",
        body: "Hello",
      },
    },
  });
  assert.ok(staged);
  assert.equal(staged.kind, "connector_write");
  assert.equal(staged.taskId, taskId);
  assert.equal(connectorWriteTaskIdFromToken(staged.token), taskId);
  assert.equal(staged.connectorCall.tool, "gmail.send");
  assert.equal(
    stageConnectorWriteApproval({
      userId: "user-1",
      workload: "mobile_chat_balanced",
      request: {
        tool: "gmail.send",
        args: { to: "a@b.co", subject: "x", body: "y" },
      },
    }),
    null,
  );
});
