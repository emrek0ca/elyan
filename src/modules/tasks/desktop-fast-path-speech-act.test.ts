import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";

// ---------------------------------------------------------------------------
// HIZLI YOL SÖZ EDİMİNİ OKUMALI.
//
// `evaluateLocalActionEvidence` söz edimi kapısını okuyordu; `evaluateDesktopFastPath`
// OKUMUYORDU. Aynı sinyalin bir kapıda okunup diğerinde okunmaması bu projede
// tekrar eden hata sınıfı.
//
// Ölçüm (25 gündelik sohbet cümlesi):
//   kapı yokken : hızlı yol 6/25 açıldı
//                 "bugün kendimi yorgun hissediyorum" → get_weather
//                 "bazen susmak konuşmaktan iyi geliyor" → desktop_os.volume
//                 "en sevdiğin film türü hangisi" → desktop_os.active_window
//   kapı varken : 0/25
//   net komutlar: 7/8 → 7/8 (değişmedi)
//
// Hızlı yol ağır anlama hattını (~2,5 sn) ve hafıza aramasını atlar; yani tam
// da anlaşılmayı gerektiren cümlede anlama kapatılıyordu.
// ---------------------------------------------------------------------------

const matcher = readFileSync(
  new URL("./desktop-capability-embedding-match.ts", import.meta.url).pathname.replace(
    /\/dist\//,
    "/src/",
  ),
  "utf8",
);
const service = readFileSync(
  new URL("./service.ts", import.meta.url).pathname.replace(/\/dist\//, "/src/"),
  "utf8",
);

test("hızlı yol kararı söz edimi kapısını içerir", () => {
  assert.ok(
    matcher.includes("capabilityAllowsSpeechActExecution"),
    "evaluateDesktopFastPath söz edimi kapısını okumuyor",
  );
  assert.ok(matcher.includes('reason: "speech_act_blocks"'));
});

test("söz edimi kapısı marj kapısından ÖNCE gelir", () => {
  const gate = matcher.indexOf("!capabilityAllowsSpeechActExecution(");
  const margin = matcher.indexOf("margin < FAST_PATH_MARGIN", gate);
  assert.ok(gate > -1, "söz edimi kapısı bulunamadı");
  assert.ok(margin > gate, "marj kapısı söz ediminden önce dönüyor");
});

test("çağıran yönlendiricinin hesapladığı söz edimini geçirir", () => {
  const call = service.indexOf("evaluateDesktopFastPath({");
  assert.ok(call > -1, "çağrı bulunamadı");
  const body = service.slice(call, call + 400);
  assert.ok(
    body.includes("speechAct: routeDecision.speechAct?.act"),
    "söz edimi çağrıda geçirilmiyor — kapı sessizce ölür",
  );
});

test("karar nesnesi söz edimini geri bildirir", () => {
  assert.ok(
    matcher.includes("speechAct: SpeechAct | null;"),
    "FastPathDecision söz edimini taşımıyor; kapının okunup okunmadığı loglanamaz",
  );
});

// ---------------------------------------------------------------------------
// GECİKME EŞİĞİ İLE GÜVENLİK EŞİĞİ AYNI SABİT OLAMAZ.
//
// `FAST_PATH_MARGIN` yanılırsa bir tur 2,5 sn yavaşlar. `LOCAL_ACTION_MARGIN`
// yanılırsa kullanıcının makinesinde yanlış iş çalışır. Tek sabit paylaşılırsa
// gecikme için yapılan bir ayar yürütme kapısını sessizce gevşetir.
// ---------------------------------------------------------------------------

test("yürütme kanıtı gecikme eşiğini kullanmaz", () => {
  const start = matcher.indexOf("export async function evaluateLocalActionEvidence");
  assert.ok(start > -1, "evaluateLocalActionEvidence bulunamadı");
  const body = matcher.slice(start, matcher.indexOf("export type FastPathDecision", start));
  assert.ok(
    body.includes("LOCAL_ACTION_MARGIN"),
    "yürütme kapısı kendi eşiğini okumuyor",
  );
  assert.equal(
    body.includes("FAST_PATH_MARGIN"),
    false,
    "yürütme kapısı gecikme eşiğine bağlı — biri değişince diğeri sessizce kayar",
  );
});

test("hızlı yol kendi eşiğini kullanır", () => {
  const start = matcher.indexOf("export async function evaluateDesktopFastPath");
  const body = matcher.slice(start);
  assert.ok(body.includes("FAST_PATH_MARGIN"));
  assert.equal(body.includes("LOCAL_ACTION_MARGIN"), false);
});
