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
