import assert from "node:assert/strict";
import test from "node:test";
import { readFileSync } from "node:fs";
import { resolveDesktopCapabilityExecutionPolicy } from "./desktop-capability-execution-policy.js";

/**
 * YETENEK İNDEKSİ ROTAYA GİRDİDİR, ÇIKTISI DEĞİL.
 *
 * ÖLÇÜLEN ARIZA (2026-08-28): "Bana bir hatırlatıcı kur: yarın 11:00 spor"
 * sunucu beyninde kalıyordu (`route: server_brain`, `capabilities: []`).
 * Model orada bir araç çağrısı üretiyor, hiçbir şey yürütmüyor ve kullanıcı
 * ya ham çağrıyı ya da uydurma bir "Hatırlatıcı eklendi" cevabını alıyordu.
 *
 * Anlamsal yetenek indeksi doğru cevabı biliyordu (`add_reminder` 0.981); tek
 * sorun yalnız masaüstü rotası SEÇİLDİKTEN SONRA sorulmasıydı — oysa rota,
 * yetenek bulunduğu için seçiliyor.
 *
 * Bu test gömme modeli gerektirmez: yükseltmenin iki koşulunun (yetki +
 * ölçülen eşik) yerinde durduğunu ve ölçümün kod içinde kayıtlı kaldığını
 * doğrular.
 */

test("only desktop-authority capabilities can escalate a turn", () => {
  // Masaüstüne yükseltme YALNIZ yetkisi `desktop` olan yeteneklerle olur.
  for (const capability of [
    "add_reminder",
    "add_calendar_event",
    "directory_tree",
    "make_directory",
    "close_app",
  ]) {
    assert.equal(
      resolveDesktopCapabilityExecutionPolicy(capability)?.authority,
      "desktop",
      capability,
    );
  }

  // `hybrid` yetenekler sunucuda da çalışabilir; onları masaüstüne göndermek
  // gereksiz gecikmedir. "1350 TL'nin KDV'si" turu `math_solve` ile eşleşiyor
  // ve orada kalmalı.
  for (const capability of ["math_solve", "document_write", "web_research"]) {
    assert.notEqual(
      resolveDesktopCapabilityExecutionPolicy(capability)?.authority,
      "desktop",
      capability,
    );
  }
});

test("the capability index alone cannot decide the route", () => {
  // ÖLÇÜM (2026-08-28): masaüstüne yükseltmeyi yetenek indeksi skoruna
  // bağlamak DENENDİ ve geri alındı. On iki örnekte boşluk temiz görünüyordu;
  // set genişletilince çöktü:
  //
  //   sunucuda kalmalı   "Yarın için motivasyon sözü ver"  0.9988
  //                      "Bu cümleyi İngilizceye çevir…"   0.9302
  //   masaüstü gereken   "Bana bir hatırlatıcı kur…"       0.9819
  //
  // Sunucu istemi gerçek masaüstü isteminden yüksek puan alıyor; hiçbir eşik
  // ikisini ayırmaz. Bu test o kararın kod tabanında kayıtlı kalmasını
  // sağlıyor: yükseltme kodu geri gelirse ölçüm de gelmeli.
  const source = readFileSync("src/modules/tasks/service.ts", "utf8");
  assert.equal(
    source.includes("DESKTOP_CAPABILITY_ROUTE_THRESHOLD"),
    false,
    "yükseltme eşiği geri gelmiş — önce ölçüm setini genişlet",
  );
  assert.ok(
    source.includes("DENENDİ VE GERİ ALINDI"),
    "geri alma gerekçesi kaynakta kalmalı",
  );
});
