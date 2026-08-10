import test from "node:test";
import assert from "node:assert/strict";
import { formatReplayReport, replayAll, type ReplayCase } from "./loop-replay.js";

/**
 * Replay korpusu — her vaka GERÇEK bir arızadan ya da onun komşusundan gelir.
 *
 * Kural: buraya hayali senaryo yazılmaz. Bir vaka ya canlıda kırıldı ya da
 * bir düzeltmenin fazla gevşemediğini kanıtlıyor. Böylece korpus büyüdükçe
 * anlamı seyrelmez.
 */
const CASES: ReplayCase[] = [
  {
    name: "chrome-kapat-yanlis-tahmine-ragmen",
    utterance: "Chrome u kapat",
    // Canlıda router isteği app_control sandı; o desktop_operator.run'a
    // eşlenip iş emrine şart olarak yazıldı.
    routerCapabilities: ["desktop_operator.run"],
    plan: [
      {
        id: "s1",
        capability: "close_app",
        args: { app_name: "Google Chrome" },
        dependsOn: [],
        description: "Chrome'u kapat",
      },
    ],
    expect: "accepted",
    note: "task 6a7ef5fb — doğru plan yanlış tahmin yüzünden reddediliyordu",
  },
  {
    name: "klasor-olustur",
    utterance: "Masaüstünde Cabir adında klasör oluştur",
    routerCapabilities: ["file_write"],
    plan: [
      {
        id: "s1",
        capability: "make_directory",
        args: { path: "~/Desktop/Cabir" },
        dependsOn: [],
        description: "Klasörü oluştur",
      },
    ],
    expect: "accepted",
    note: "router file_write tahmin etse de doğru araç make_directory",
  },
  {
    name: "yeni-sekme-arama-degil",
    utterance: "Yeni sekme aç",
    routerCapabilities: ["browser_control"],
    plan: [
      {
        id: "s1",
        capability: "browser_control",
        args: { action: "new_tab" },
        dependsOn: [],
        description: "Yeni sekme aç",
      },
    ],
    expect: "accepted",
  },
  {
    name: "uydurulmus-tarayici-eylemi-reddedilir",
    utterance: "Chrome u kapat",
    routerCapabilities: ["browser_control"],
    plan: [
      {
        id: "s1",
        capability: "browser_control",
        // Canlıda üretilen geçersiz değer: böyle bir eylem yok.
        args: { action: "close_tab" },
        dependsOn: [],
        description: "Sekmeyi kapat",
      },
    ],
    expect: "rejected",
    expectedIssuePattern: /is not a valid value/u,
    note: "enum kapısı — 'Geçersiz tarayıcı eylemi.' arızasının kaynağı",
  },
  {
    name: "olmayan-yetenek-reddedilir",
    utterance: "Bilgisayarı kapat",
    routerCapabilities: ["close_app"],
    plan: [
      {
        id: "s1",
        capability: "system_shutdown",
        args: {},
        dependsOn: [],
        description: "Sistemi kapat",
      },
    ],
    expect: "rejected",
    expectedIssuePattern: /not in the desktop manifest/u,
    note: "gevşetme fazla ileri gitmemeli: manifest dışı yetenek geçmez",
  },
  {
    name: "zorunlu-argumansiz-adim-reddedilir",
    utterance: "Şu dosyayı oku",
    routerCapabilities: ["file_read"],
    plan: [
      {
        id: "s1",
        capability: "file_read",
        args: {},
        dependsOn: [],
        description: "Oku",
      },
    ],
    expect: "rejected",
    expectedIssuePattern: /requires args\.path/u,
  },
  {
    name: "koksuz-yol-reddedilir",
    utterance: "notlar.txt dosyasını oku",
    routerCapabilities: ["file_read"],
    plan: [
      {
        id: "s1",
        capability: "file_read",
        args: { path: "notlar.txt" },
        dependsOn: [],
        description: "Oku",
      },
    ],
    expect: "rejected",
    expectedIssuePattern: /explicit root/u,
  },
  {
    name: "gecersiz-bagimlilik-reddedilir",
    utterance: "Araştır ve yaz",
    routerCapabilities: ["web_research", "document_write"],
    plan: [
      {
        id: "s1",
        capability: "web_research",
        args: { query: "public kaynak" },
        dependsOn: ["s2"],
        description: "Araştır",
      },
    ],
    expect: "rejected",
    expectedIssuePattern: /dependsOn must reference an earlier step/u,
  },
];

test("the desktop chain replays real failures without regressing", () => {
  const outcomes = replayAll(CASES);
  const failed = outcomes.filter((outcome) => !outcome.passed);
  assert.equal(
    failed.length,
    0,
    `\n${formatReplayReport(outcomes)}`,
  );
});

test("replay covers both directions: correct plans pass and bad plans are stopped", () => {
  // Korpusun tek yöne kaymadığını doğruluyoruz. Yalnız "kabul" vakası
  // biriktirmek doğrulayıcıyı gevşetmeye, yalnız "ret" biriktirmek de
  // sıkılaştırmaya sürükler.
  const accepted = CASES.filter((testCase) => testCase.expect === "accepted");
  const rejected = CASES.filter((testCase) => testCase.expect === "rejected");
  assert.ok(accepted.length >= 3, "kabul vakası az");
  assert.ok(rejected.length >= 3, "ret vakası az");
});
