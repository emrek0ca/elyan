import test from "node:test";
import assert from "node:assert/strict";
import { isDeterministicDesktopFastWorkOrder } from "./desktop-work-order.js";
import type { CommandRouteDecision } from "../routing-policy/service.js";

/**
 * Hızlı yol kapısının SINIRI.
 *
 * Bu testler yeni ANLAMSAL kapıyı değil, onun neden gerektiğini sabitliyor:
 * deterministik ayrıştırıcı bir kelime desenidir ve Türkçe eklerde kırılır.
 * Anlamsal kapının kendisi e5'e (semantic compute worker) bağlı olduğundan
 * birim testinde koşturulmaz; ölçümü routing-eval ve replay üzerinden yapılır.
 */

function desktopRoute(): CommandRouteDecision {
  return {
    route: "desktop_runtime",
    mode: "executable_task",
    capabilities: [],
    privacyClass: "public_text",
    requiresApproval: false,
    reason: "fast_path_test",
    intent: "desktop_cowork",
    confidence: 0.9,
    requiredRuntime: "desktop",
    privacyLevel: "medium",
    shouldAskClarification: false,
    failClosedReason: "desktop_runtime_selected_target",
    selectedWorkload: "desktop_handoff",
    taskRoute: {
      target: "desktop_runtime",
      operationalRoute: "desktop_runtime",
      executionPlan: ["desktop_runtime"],
      reason: "fast_path_test",
      needsDesktop: true,
      needsPrivateDesktopData: false,
      needsUserApproval: false,
      requiredCapabilities: [],
    },
  } as CommandRouteDecision;
}

test("the deterministic parser still covers the shapes it was written for", () => {
  for (const message of [
    "Spotify uygulamasını kapat",
    "Finder aç",
    "Notlar başlat",
  ]) {
    assert.equal(
      isDeterministicDesktopFastWorkOrder(desktopRoute(), message),
      true,
      message,
    );
  }
});

test("the deterministic parser misses ordinary phrasings — this is why the gate is semantic now", () => {
  // Hepsi tek ve net masaüstü komutu; hiçbiri kelime desenine uymuyor.
  // Eskiden bu istekler ~2.5 sn'lik anlama hattını boşuna ödüyordu.
  //
  // GÜNCELLEME (2026-08-22): "Terminali kapatır mısın" ARTIK deterministik
  // olarak çözülüyor — yapısal yuva çıkarımı (024a7f06) uygulama adını ekli
  // hâlde tanıyabiliyor. Bu bir iyileşme; test onu yansıtacak şekilde
  // güncellendi, kod geri alınmadı.
  //
  // Hata nasıl gözden kaçtı: 024a7f06 turunda tam test kümesi koşulmadı.
  // Aynı ölçüm hijyeni dersi — bkz. c257398b'nin 9 gizli regresyonu.
  assert.equal(
    isDeterministicDesktopFastWorkOrder(desktopRoute(), "Terminali kapatır mısın"),
    true,
    "yapısal yuva çıkarımı bu ifadeyi artık çözüyor",
  );

  // Bunlar hâlâ kelime desenine uymuyor; semantik kapının varlık sebebi.
  for (const message of ["chrome kapansın artık", "şu uygulamadan çık"]) {
    assert.equal(
      isDeterministicDesktopFastWorkOrder(desktopRoute(), message),
      false,
      message,
    );
  }
});

test("the deterministic fast path never fires off the desktop route", () => {
  const chatRoute = { ...desktopRoute(), route: "server_brain", taskRoute: undefined } as CommandRouteDecision;
  assert.equal(
    isDeterministicDesktopFastWorkOrder(chatRoute, "Spotify uygulamasını kapat"),
    false,
  );
});
