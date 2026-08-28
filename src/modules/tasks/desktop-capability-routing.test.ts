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

test("the escalation threshold sits between the measured clusters", () => {
  const source = readFileSync("src/modules/tasks/service.ts", "utf8");
  const match = source.match(
    /const DESKTOP_CAPABILITY_ROUTE_THRESHOLD = ([\d.]+);/,
  );
  assert.ok(match, "eşik sabiti bulunamadı");
  const threshold = Number(match[1]);

  // Ölçülen dağılım (yorumda tam listesi var):
  //   masaüstü gereken, en düşük eşleşme            0.981
  //   sunucuda kalmalı, masaüstü-yetkili en yüksek  0.873
  assert.ok(
    threshold > 0.873,
    `eşik ${threshold}, sunucuda kalması gerekenlerin en yükseğinin üstünde olmalı`,
  );
  assert.ok(
    threshold < 0.981,
    `eşik ${threshold}, masaüstü gerekenlerin en düşüğünün altında olmalı`,
  );
});

test("an escalated decision is coherent, not half-changed", () => {
  // İlk denemede yalnız `route` ve `requiredRuntime` değiştirilmişti; kalan
  // alanlar sohbet kararının değerlerinde kaldı ve kullanıcı masaüstüne
  // yönlenen bir turda "Bu istek sohbet olarak işlenecek." gördü.
  const source = readFileSync("src/modules/tasks/service.ts", "utf8");
  const block = source.slice(
    source.indexOf("escalated to desktop by capability index"),
  ).slice(0, 1200);

  for (const field of [
    'route: "desktop_runtime"',
    'requiredRuntime: "desktop"',
    'mode: "executable_task"',
    "userFacingMessage:",
  ]) {
    assert.ok(block.includes(field), `yükseltme ${field} alanını da ayarlamalı`);
  }
});
