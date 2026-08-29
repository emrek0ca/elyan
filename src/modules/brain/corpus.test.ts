import assert from "node:assert/strict";
import test from "node:test";
import {
  buildBrainCorpusGuidanceBlock,
  buildBrainCorpusRetrievalQuery,
  detectBrainCorpusDomains,
  ELYAN_BRAIN_CORPUS_VERSION,
  getBrainCorpusManifest,
  selectBrainCorpusDomains,
} from "./corpus.js";
import { shapePublicBrainProfile } from "./service.js";

test("brain corpus guidance is injected for design/data prompts", async () => {
  const domains = detectBrainCorpusDomains("Profesyonel bir PDF raporu tasarla, tablo da olsun");
  const block = await buildBrainCorpusGuidanceBlock(
    "Profesyonel bir PDF raporu tasarla, tablo da olsun",
    domains,
  );
  assert.ok(block, "guidance block should not be null for a design/data request");
  assert.match(block!, /corpus guidance/i);
  // At most GUIDANCE_DOMAIN_LIMIT (2) sections, each capped — keep it token-cheap.
  assert.ok(block!.length < 1600, "guidance block should stay compact");
});

test("brain corpus guidance is empty when no domain matches", async () => {
  const block = await buildBrainCorpusGuidanceBlock("naber nasilsin", []);
  assert.equal(block, null);
});

test("brain corpus manifest is versioned and hash-backed", async () => {
  const manifest = await getBrainCorpusManifest();

  assert.equal(manifest.length, 13);
  assert.equal(new Set(manifest.map((item) => item.id)).size, manifest.length);
  assert.ok(manifest.every((item) => item.version === ELYAN_BRAIN_CORPUS_VERSION));
  assert.ok(manifest.every((item) => /^[a-f0-9]{64}$/.test(item.contentHash)));
  assert.deepEqual(
    manifest.map((item) => item.domain).sort(),
    [
      "capabilities",
      "code",
      "data",
      "design",
      "language",
      "memory",
      "onboarding",
      "product",
      "reasoning",
      "safety",
      "skills",
      "support",
      "tasks",
    ],
  );
});

test("stable product questions select the knowledge corpus from registry metadata", async () => {
  const selected = await selectBrainCorpusDomains({
    prompt: "Elyan masaüstü ne işe yarar?",
    queryVector: null,
  });
  assert.equal(selected[0]?.domain, "product");
  assert.equal(selected[0]?.source, "registry");
});

test("brain corpus domain mapper selects relevant domains", () => {
  assert.deepEqual(detectBrainCorpusDomains("Modern bir website tasarla ve PDF olarak raporla"), [
    "design",
    "data",
  ]);
  assert.deepEqual(detectBrainCorpusDomains("Bu TypeScript API bugini debug edip test yaz"), ["code"]);
  assert.deepEqual(detectBrainCorpusDomains("Bu tabloyu analiz et ve grafik oner"), ["data"]);
  assert.deepEqual(detectBrainCorpusDomains("Elyan hangi skill ile desktop runtime kullanmali?"), ["skills"]);
});

test("brain corpus retrieval query keeps original prompt and adds domain hints", () => {
  const query = buildBrainCorpusRetrievalQuery("Kod kalitesini artir ve regression test ekle");

  assert.match(query, /Kod kalitesini artir/);
  assert.match(query, /Elyan Code Engineering Protocol/);
  assert.match(query, /architecture/);
});

test("public brain profile exposes corpus readiness without corpus content", () => {
  const shaped = shapePublicBrainProfile({
    chat: {
      activeSharedModel: null,
      activeUserModel: null,
      configuredBaseModel: "hidden-model",
      resolvedBaseModel: "hidden-model",
      resolvedBaseModelSource: "hidden",
      availableModels: ["hidden-model"],
      activeMobileDefaultProfile: null,
      fallbackStatus: null,
      currentServingPolicy: null,
      activeArtifact: null,
      activeKnowledgeCorpus: {
        mode: "shared_global",
        readyDocuments: 8,
        readyDatasets: 0,
        latestDocumentUpdatedAt: null,
        latestDatasetUpdatedAt: null,
        systemCorpus: {
          enabled: true,
          corpusVersion: ELYAN_BRAIN_CORPUS_VERSION,
          expectedDocuments: 8,
          readyDocuments: 8,
          readyChunks: 24,
          domains: ["design", "code"],
          categories: [
            {
              domain: "design",
              version: ELYAN_BRAIN_CORPUS_VERSION,
              readyDocuments: 1,
              readyChunks: 3,
              latestUpdatedAt: null,
              content: "must_not_leak",
            },
          ],
        },
      },
    },
  } as unknown as Parameters<typeof shapePublicBrainProfile>[0]) as Record<string, unknown>;

  const serialized = JSON.stringify(shaped);
  assert.doesNotMatch(serialized, /hidden-model/);
  assert.doesNotMatch(serialized, /must_not_leak/);
  assert.match(serialized, /systemCorpus/);
  assert.match(serialized, /design/);
});

/**
 * CANLI ARIZA (mobil, 2026-08-29): "Neler yapabilirsin ve bilgiyi nereden
 * alıyorsun?" turunda yalnız `## Neler yapabilir` enjekte edildi;
 * `## Bilgi nereden gelir` isteme hiç girmedi ve model kaynak sırasını
 * UYDURDU — "önce sohbet, ardından güncel web kaynakları ve eğitim verilerim"
 * dedi. Korpusun yazdığı sıra ise konuşma → hafıza → tipli sağlayıcı →
 * korpus → (gerekiyorsa) web. Kullanıcıya sistemin kendi mimarisi yanlış
 * anlatıldı; bu, cevabın kalitesinden önce bir DOĞRULUK sorunudur.
 */
test("a two-part question reaches both corpus sections", async () => {
  const block = await buildBrainCorpusGuidanceBlock(
    "Neler yapabilirsin ve bilgiyi nereden alıyorsun?",
    ["capabilities"],
  );
  const headings = block?.match(/^##\s+.*$/gm) ?? [];
  assert.ok(
    headings.some((heading) => /Neler yapabilir/.test(heading)),
    "yetenek bölümü gelmeli",
  );
  assert.ok(
    headings.some((heading) => /Bilgi nereden gelir/.test(heading)),
    "kaynak sırası bölümü gelmeli",
  );
});

/**
 * Dokümanın `#` başlığı bir rehber bölümü DEĞİLDİR. Aday listesinde kaldığı
 * için hiçbir bölümün eşleşmediği turlarda o seçiliyor ve isteme tek bir
 * yönerge içermeyen 106 karakterlik bir blok giriyordu.
 */
test("the document title is never injected as guidance", async () => {
  for (const [prompt, domain] of [
    ["Neden internete bakmadın?", "capabilities"],
    ["Görev neden bekliyor?", "support"],
  ] as const) {
    const block = await buildBrainCorpusGuidanceBlock(prompt, [domain]);
    assert.ok(block, prompt);
    assert.ok(/^##\s+/m.test(block!), `en az bir '##' bölümü gelmeli: ${prompt}`);
    assert.doesNotMatch(block!, /^#\s+Elyan/m, prompt);
  }
});

/**
 * İki alan eşleştiğinde bütçe büyümez: ikinci bölüm yalnız TEK alan
 * eşleştiğinde (soru tek konuda ama çok parçalı olduğunda) alınır.
 */
test("guidance stays token-disciplined when two domains match", async () => {
  const block = await buildBrainCorpusGuidanceBlock(
    "rapor tablosu ve pdf tasarımı yap",
    ["design", "data"],
  );
  assert.ok(block);
  assert.ok(block!.length < 1600, `blok kompakt kalmalı, ${block!.length}`);
});
