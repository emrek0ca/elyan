import assert from "node:assert/strict";
import test from "node:test";
import { buildDesktopWorkOrder } from "./desktop-work-order.js";
import type { CommandRouteDecision } from "../routing-policy/service.js";

// ---------------------------------------------------------------------------
// TÜRKÇE EK TOLERANSI — PLANLAMA SİNYALLERİ.
//
// Bu dosyadaki niyet kalıpları `\b` ile kök arıyordu; Türkçe eklemeli olduğu
// için ekli biçimlerde SESSİZCE ölüyorlardı. Ölçülen kaçırmalar:
//
//   "kaydeder misin" / "indirir misin"  → kaydetme niyeti görülmüyordu
//   "dosyayı kaydet" / "raporu hazırla" → belge ismi görülmüyordu
//   "terminali kapat" / "şu komutu koştur" → terminal bağlamı görülmüyordu
//   "uygulamayı kapat" / "ekranda ne var"  → bilgisayar görevi sayılmıyordu
//
// `unicodeWordPattern` bunu çözmez (yalnız sınırı Unicode'a taşır); ek
// toleransı için `trStemPattern` gerekir.
// ---------------------------------------------------------------------------

function desktopRoute(): CommandRouteDecision {
  return {
    route: "desktop_runtime",
    capabilities: [],
    taskRoute: { operationalRoute: "desktop_runtime" },
  } as unknown as CommandRouteDecision;
}

function goalKindFor(message: string): string {
  const order = buildDesktopWorkOrder({
    message,
    title: message,
    routeDecision: desktopRoute(),
    requestedCapabilities: [],
  } as never);
  return order.goal.kind;
}

test("ekli biçimler görev türünü kaybettirmez", () => {
  for (const [message, expected] of [
    ["terminali kapat", "terminal_task"],
    ["şu komutu koştur", "terminal_task"],
    ["uygulamayı kapat", "computer_task"],
    ["ekranda ne var", "computer_task"],
    ["sunumu hazırla", "presentation_task"],
    ["slaytları düzenle", "presentation_task"],
  ] as const) {
    assert.equal(goalKindFor(message), expected, message);
  }
});

test("komutan/komuta gibi kelimeler terminal görevi saymaz", () => {
  for (const message of ["ordu komutanlığı hakkında bilgi ver", "komuta kademesi nedir"]) {
    assert.notEqual(goalKindFor(message), "terminal_task", message);
  }
});

// ---------------------------------------------------------------------------
// MENÜ HEDEFLE ÇELİŞMEMELİ.
//
// Canlı arıza (görev fd3acf73): "masaüstüne kediler hakkında rapor hazırla ve
// kaydet" isteğinde hedef doğru çıktı (document_task) ama anlamsal sözleşme
// [desktop_operator.run, desktop_operator_run, document_read] önerdi — hiçbiri
// belge YAZMIYOR. Menüde yazıcı olmayınca planlayıcı elindeki tek "dış dünya"
// aracına uzandı: tarayıcıyı sürüp Wikipedia'ya gitmek.
// ---------------------------------------------------------------------------

function documentWorkflowRoute(): CommandRouteDecision {
  return {
    route: "desktop_runtime",
    capabilities: [],
    taskRoute: {
      operationalRoute: "desktop_runtime",
      semanticDesktopContract: {
        contract: "elyan.semantic_desktop_dispatch.v1",
        route: "desktop_runtime",
        intent: "document_workflow",
        requiredSemanticCapabilities: [
          "desktop_operator.run",
          "desktop_operator_run",
          "document_read",
        ],
        requiredLocalContext: [],
        sideEffectLevel: "write",
        confidence: 0.7,
        evidence: [],
      },
    },
  } as unknown as CommandRouteDecision;
}

function capabilitiesFor(message: string): string[] {
  const order = buildDesktopWorkOrder({
    message,
    title: message,
    routeDecision: documentWorkflowRoute(),
    requestedCapabilities: [],
  } as never);
  return order.requiredCapabilities;
}

test("belge görevine yazıcı eklenir", () => {
  const capabilities = capabilitiesFor("masaüstüne kediler hakkında bir rapor hazırla ve kaydet");
  assert.ok(
    capabilities.includes("document_write"),
    `menüde yazıcı yok: ${capabilities.join(", ")}`,
  );
});

test("ekran bağlamı yoksa belge görevinden ekran otomasyonu düşer", () => {
  const capabilities = capabilitiesFor("masaüstüne kediler hakkında bir rapor hazırla ve kaydet");
  assert.equal(
    capabilities.some((capability) => capability.startsWith("desktop_operator")),
    false,
    `bilgi görevinde ekran otomasyonu kaldı: ${capabilities.join(", ")}`,
  );
});

test("ekran görüntüsü artık GENERIC yürütücüye düşmez", () => {
  // Bu vaka eskiden bu dosyada "ekran otomasyonu korunmalı" diye kilitliydi:
  // ekran görüntüsü alıp KAYDEDEN bir yetenek olmadığı için tek yol
  // `desktop_operator` idi. Canlı arıza (görev 234fbf31) tam oradan çıktı —
  // iki generic çağrı "başarılı" dedi, dosya oluşmadı, doğrulama görevi
  // düşürdü. `screen_capture` eklendiği için geçici çözüm de gereksiz.
  const capabilities = capabilitiesFor("ekran görüntüsü al ve masaüstüne kaydet");
  assert.deepEqual(capabilities, ["screen_capture"]);
});

test("gerçek karma işlerde ekran otomasyonu KORUNUR", () => {
  // Bunlar ekran/tarayıcı yüzeyine gerçekten muhtaç; kapı onları elemez.
  for (const message of [
    "ekrandaki tabloyu bir word belgesine aktar",
    "chrome'daki sayfayı pdf olarak kaydet",
  ]) {
    const capabilities = capabilitiesFor(message);
    assert.ok(
      capabilities.some((capability) => capability.startsWith("desktop_operator")),
      `${message} → ekran erişimi düştü: ${capabilities.join(", ")}`,
    );
  }
});
