import assert from "node:assert/strict";
import test from "node:test";
import {
  buildMcpCapabilityIndex,
  collectStoredMcpTools,
  mcpToolManifestEntry,
} from "./mcp-capability-bridge.js";

const server = (overrides: Record<string, unknown> = {}) => ({
  status: "connected",
  metadata: {
    probe: {
      tools: [
        {
          capabilityId: "mcp:google_calendar:list_events",
          toolName: "list_events",
          sideEffectClass: "read",
          riskClass: "low",
          requiresApproval: false,
        },
        {
          capabilityId: "mcp:google_calendar:create_event",
          toolName: "create_event",
          sideEffectClass: "write",
          riskClass: "elevated",
          requiresApproval: true,
        },
      ],
    },
  },
  ...overrides,
});

test("yoklanmış araçlar derleyici kataloğuna girer", () => {
  const tools = collectStoredMcpTools([server()]);
  assert.equal(tools.length, 2);
  assert.equal(tools[0].capabilityId, "mcp:google_calendar:list_events");
  assert.equal(tools[1].requiresApproval, true);
});

test("KAPATILMIŞ sunucunun araçları görünmez", () => {
  // Kullanıcının kapattığı bir sunucunun aracı planlanabilir olmamalı.
  assert.deepEqual(collectStoredMcpTools([server({ status: "revoked" })]), []);
});

test("yoklanmamış sunucu araç üretmez", () => {
  assert.deepEqual(collectStoredMcpTools([{ status: "configured", metadata: {} }]), []);
  assert.deepEqual(collectStoredMcpTools(null), []);
});

test("aynı araç iki sunucuda ilan edilse tek kayıt olur", () => {
  assert.equal(collectStoredMcpTools([server(), server()]).length, 2);
});

test("MCP olmayan ad kataloga giremez", () => {
  const tools = collectStoredMcpTools([
    {
      status: "connected",
      metadata: { probe: { tools: [{ capabilityId: "desktop_operator.run" }] } },
    },
  ]);
  assert.deepEqual(tools, []);
});

test("SINIF BİLİNMİYORSA araç onay ister ve yazıcı sayılır", () => {
  // Bilinmeyen bir aracı salt-okuma saymak, kullanıcının görmediği bir yan
  // etkiye kapı açmaktır.
  const entry = mcpToolManifestEntry({ capabilityId: "mcp:x:y" });
  assert.equal(entry.requiresApproval, true);
  assert.equal(entry.sideEffectClass, "write");
  assert.equal(entry.mutatesPath, false);
});

test("indeks capability adıyla sorgulanabilir", () => {
  const index = buildMcpCapabilityIndex(collectStoredMcpTools([server()]));
  assert.equal(index.get("mcp:google_calendar:list_events")?.requiresApproval, false);
  assert.equal(index.get("mcp:google_calendar:create_event")?.sideEffectClass, "write");
  assert.equal(index.get("yok"), undefined);
});

test("a connected tool carries the text that makes it findable", () => {
  // Bu fonksiyon yalnız dört alan üretip `as` ile tam manifest girdisi gibi
  // davranıyordu. İki katmanda kırılıyordu:
  //
  //   1. Anlamsal indeks pasajı displayName/description/usage/whenToUse/
  //      utterances alanlarından kurar; hepsi boş olduğu için bağlı bir
  //      uygulamanın aracı hiçbir sorguda bulunamıyordu.
  //   2. Dizi alanları YOK olduğu için pasaj kurucusu `...entry.whenToUse`
  //      üzerinde "undefined is not iterable" fırlatıyor, hata öneri
  //      motorunun catch'ine düşüyor ve fonksiyon BOŞ dönüyordu — yani bağlı
  //      tek bir MCP sunucusu, YEREL yetenek önerilerini de susturuyordu.
  const entry = mcpToolManifestEntry({
    capabilityId: "mcp:notion:create-pages",
    toolName: "create-pages",
    serverName: "Notion",
    sideEffectClass: "write",
    requiresApproval: true,
    description: "Notion'da yeni sayfa oluşturur.",
  });

  // Dizi alanları her koşulda dizi olmalı: aşağıdaki yayma bunu ister.
  for (const field of ["whenToUse", "utterances", "requiredArgs", "fewShots"] as const) {
    assert.ok(Array.isArray(entry[field]), `${field} dizi olmalı`);
  }
  assert.doesNotThrow(() => [...entry.whenToUse, ...entry.utterances]);

  // Sunucunun adı ve aracın açıklaması gömmeye ulaşmalı.
  assert.match(entry.displayName, /Notion/);
  assert.match(entry.description, /sayfa oluşturur/);
  assert.ok(entry.utterances.includes("Notion"));

  // Güvenlik sınıflandırması değişmemeli.
  assert.equal(entry.requiresApproval, true);
  assert.equal(entry.sideEffectClass, "write");
  assert.equal(entry.sideEffect, true);
  assert.equal(entry.fallbackExecutionEligible, false);
});

test("an unclassified connected tool still fails closed", () => {
  const entry = mcpToolManifestEntry({ capabilityId: "mcp:unknown:do-something" });
  assert.equal(entry.sideEffectClass, "write");
  assert.equal(entry.requiresApproval, true);
  assert.equal(entry.questionSafeObservation, false);
  // Ad çözülemese bile girdi kullanılabilir kalmalı.
  assert.ok(Array.isArray(entry.whenToUse));
  assert.equal(entry.name, "mcp:unknown:do-something");
});
