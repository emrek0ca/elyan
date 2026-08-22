import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";
import {
  EPISODE_PRECEDENT_MIN_OBSERVATIONS,
  EPISODE_PRECEDENT_MIN_SIMILARITY,
  summarizeRoutePrecedent,
} from "./episodic-decisions.js";

// ---------------------------------------------------------------------------
// KATMAN 1 + 2 BURADA BULUŞUR.
//
// Katmanlar ayrıştığında sistem kullanıcıya "tam olarak ne istiyorsun?" diye
// soruyordu — aynı cümleyi daha önce çalıştırmış olmasına rağmen. Canlı kanıt:
//   b2845b50 (14:59) "masaüstüne … pdf" → desktop_runtime
//   63553c0b (17:02) AYNI CÜMLE        → server_brain + netleştirme sorusu
//
// Emsal etiketi TAŞIMA başarısı değil KULLANICI sonucudur; yoksa çöp PDF
// üreten `server_brain → completed` turları "başarı" sayılırdı.
// ---------------------------------------------------------------------------

function episode(
  route: string,
  outcome: "fulfilled" | "degraded" | "unfulfilled",
  similarity = 1,
) {
  return { message: "m", route, outcome, similarity, observedAt: "" };
}

test("başarılı geçmiş rota emsal olur", () => {
  const precedent = summarizeRoutePrecedent([
    episode("desktop_runtime", "fulfilled"),
    episode("desktop_runtime", "fulfilled"),
    episode("server_brain", "unfulfilled"),
  ]);
  assert.equal(precedent?.route, "desktop_runtime");
  assert.equal(precedent?.fulfilled, 2);
});

test("tek gözlem emsal sayılmaz", () => {
  assert.equal(
    summarizeRoutePrecedent([episode("desktop_runtime", "fulfilled")]),
    null,
  );
});

test("uzak benzerlik hiç sayılmaz", () => {
  // "benzer konu" yetmez; emsal ancak çok benzer ifadeden çıkar.
  assert.equal(
    summarizeRoutePrecedent([
      episode("desktop_runtime", "fulfilled", 0.8),
      episode("desktop_runtime", "fulfilled", 0.9),
    ]),
    null,
  );
});

test("geçmişi kötü olan rota emsal olmaz", () => {
  assert.equal(
    summarizeRoutePrecedent([
      episode("server_brain", "unfulfilled"),
      episode("server_brain", "unfulfilled"),
    ]),
    null,
  );
});

test("berabere kalan tarih emsal üretmez", () => {
  assert.equal(
    summarizeRoutePrecedent([
      episode("desktop_runtime", "fulfilled"),
      episode("desktop_runtime", "fulfilled"),
      episode("server_brain", "fulfilled"),
      episode("server_brain", "fulfilled"),
    ]),
    null,
  );
});

test("degraded ne ödül ne ceza", () => {
  assert.equal(
    summarizeRoutePrecedent([
      episode("desktop_runtime", "degraded"),
      episode("desktop_runtime", "degraded"),
    ]),
    null,
  );
});

test("eşikler makul", () => {
  assert.ok(EPISODE_PRECEDENT_MIN_SIMILARITY >= 0.9);
  assert.ok(EPISODE_PRECEDENT_MIN_OBSERVATIONS >= 2);
});

test("emsal, netleştirme dalından ÖNCE okunuyor", () => {
  const source = readFileSync(
    new URL("./service.ts", import.meta.url).pathname.replace(/\/dist\//, "/src/"),
    "utf8",
  );
  const recall = source.indexOf("summarizeRoutePrecedent(");
  const clarification = source.indexOf(
    "Anlama katmanları bu isteğin sunucu mu masaüstü mü",
  );
  assert.ok(recall > -1, "emsal hiç okunmuyor");
  assert.ok(recall < clarification, "emsal netleştirmeden SONRA okunuyor");
});
