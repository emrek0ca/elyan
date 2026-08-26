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
  resetConnectorBiasCacheForTests,
} from "./connector-tools.js";
import { resetSemanticBackgroundForTests } from "../../core/understanding/semantic-background.js";
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
    // Tam eşleşme (kosinüs 1.0) require bandındadır: net connector isteği.
    assert.equal(hint?.enforcement, "require");
  } finally {
    resetSemanticComputeWorkerForTests();
  }
});

test("borderline semantic scores produce a soft prefer hint, not a hard requirement", async () => {
  // Canlı bug: "Su kaç deredece kaynar" gmail.search'e 0.7997 ile eşleşti ve
  // sert şart tüm provider zincirini required_connector_tool_missing'e düşürdü.
  // 0.78-0.82 bandı yalnız önceliklendirme ipucu olmalı.
  resetSemanticComputeWorkerForTests();
  const borderlineQueryVector = new Array<number>(384).fill(0);
  borderlineQueryVector[0] = 0.8; // gmail.search çapasına kosinüs 0.8
  borderlineQueryVector[10] = 0.6; // birim norm tamamlayıcısı (kullanılmayan eksen)
  setSemanticComputeDispatcherForTests(async ({ texts }) =>
    texts.map((text) =>
      text.toLowerCase().startsWith("query:")
        ? borderlineQueryVector
        : connectorSemanticPassageVector(text),
    ),
  );
  try {
    const hint = await selectSemanticConnectorReadToolHint(
      "Su kaç deredece kaynar",
      gmailReadContracts(),
    );
    assert.equal(hint?.tool, "gmail.search");
    assert.ok((hint?.score ?? 0) < 0.82);
    assert.equal(hint?.enforcement, "prefer");
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

test("semantic connector contract gate narrows on hint, keeps all on miss", () => {
  const contracts = CONNECTOR_TOOL_CONTRACTS.filter(
    (entry) => entry.permission === "read",
  ).map((entry) => entry.contract);
  // İpucu yoksa reklam listesi sökülmez — araçsız kalan model "erişimim yok"
  // diyordu; yürütme kapıları (scope/izin) zaten ayrıca devrede.
  assert.deepEqual(
    connectorContractsForSemanticReadHint(contracts, null),
    contracts,
  );
  const selected = connectorContractsForSemanticReadHint(
    contracts,
    "gmail.search",
  );
  assert.equal(selected.length, 1);
  assert.match(selected[0] ?? "", /^gmail\.search\b/u);
  // Reklamda olmayan bir ipucu aracı da listeyi boşaltmaz (slack artık gerçek
  // bir read aracı olduğu için daralma örneği olarak kullanılamaz).
  assert.deepEqual(
    connectorContractsForSemanticReadHint(contracts, "linear.search"),
    contracts,
  );
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

// ── Notion + GitHub kataloğa bağlandı ────────────────────────────────
// integration_connections'ta connected duran notion/github hesapları katalogda
// araç taşımıyordu — bağlı hesap beyne bağlanmamıştı.

test("notion.search ve github.search read sözleşmesi olarak kataloğa girer", () => {
  const names = CONNECTOR_TOOL_CONTRACTS.map((entry) => entry.name);
  assert.ok(names.includes("notion.search"));
  assert.ok(names.includes("github.search"));
  assert.equal(isConnectorTool("notion.search"), true);
  assert.equal(isConnectorTool("github.search"), true);
});

test("scope'suz notion/github grant'ları read araçlarını reklam eder", () => {
  const advertised = connectorToolsForCapabilityGrants(
    [
      { provider: "notion", capabilities: ["notion"], scopes: [] },
      {
        provider: "github",
        capabilities: ["github"],
        scopes: ["read:user", "repo", "user:email"],
      },
    ],
    (_provider, granted, required) =>
      required.every((scope) => granted.includes(scope)),
  ).map((entry) => entry.name);
  assert.ok(advertised.includes("notion.search"));
  assert.ok(advertised.includes("github.search"));
  // Google araçları scope yoksa reklam edilmez — grant sınırı korunuyor.
  assert.equal(advertised.includes("gmail.search"), false);
});

test("a candidate that resembles every ordinary sentence cannot force a tool call", async () => {
  // CANLI HATA (ölçüldü 2026-08-26, 20 etiketli mesaj): ham kosinüs bu uzayda
  // neredeyse her cümleye yüksek skor veriyordu. "teşekkürler" 0.852,
  // "merhaba nasılsın" 0.849, "bir fıkra anlat" 0.831 — üçü de 0.82 sert
  // bandında, yani model bu mesajlarda connector aracı çağırmaya ZORLANIYORDU.
  // On sıradan mesajın beşi.
  //
  // Burada gmail.search çapası, arka plan havuzundaki SIRADAN cümlelerle aynı
  // eksene oturtulur: yani "her şeye benzeyen" bir aday. Ham skoru 1.0 olsa
  // bile özgüllüğü sıfırdır ve ipucu üretilmemelidir.
  resetSemanticComputeWorkerForTests();
  resetSemanticBackgroundForTests();
  resetConnectorBiasCacheForTests();
  setSemanticComputeDispatcherForTests(async ({ texts }) =>
    texts.map((text) =>
      text.toLowerCase().startsWith("query:")
        ? semanticTestVector(0)
        : // Hem aday hem arka plan aynı eksende: hub adayı.
          semanticTestVector(0),
    ),
  );
  try {
    const hint = await selectSemanticConnectorReadToolHint(
      "teşekkürler",
      gmailReadContracts(),
    );
    assert.equal(hint, null);
  } finally {
    resetSemanticComputeWorkerForTests();
    resetSemanticBackgroundForTests();
    resetConnectorBiasCacheForTests();
  }
});

test("a candidate that is specific to the query still produces a hint", async () => {
  // Kapının karşı tarafı: arka plan BAŞKA bir eksende olduğunda gmail.search
  // yüksek skorunu hak eder ve ipucu üretilmelidir. Kapı gürültüyü eler,
  // sinyali değil.
  resetSemanticComputeWorkerForTests();
  resetSemanticBackgroundForTests();
  resetConnectorBiasCacheForTests();
  setSemanticComputeDispatcherForTests(async ({ texts }) =>
    texts.map((text) => {
      if (text.toLowerCase().startsWith("query:")) return semanticTestVector(0);
      // Arka plan cümleleri gmail çapasına DİK bir eksende durur.
      if (!text.toLowerCase().includes("gmail")) return semanticTestVector(7);
      return connectorSemanticPassageVector(text);
    }),
  );
  try {
    const hint = await selectSemanticConnectorReadToolHint(
      "Bugün gelen mailler",
      gmailReadContracts(),
    );
    assert.equal(hint?.tool, "gmail.search");
    assert.equal(hint?.enforcement, "require");
  } finally {
    resetSemanticComputeWorkerForTests();
    resetSemanticBackgroundForTests();
    resetConnectorBiasCacheForTests();
  }
});
