import assert from "node:assert/strict";
import test from "node:test";
import { existsSync } from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { NlpDaemon } from "./nlp-daemon.js";

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const BIN = path.resolve(__dirname, "../../bin/elyan_nlp");

// memory.ts lexicalOverlapScore + turkishLower'ın birebir kopyası — parity
// kontrolü için (fonksiyonlar export edilmiyor; semantik değişirse bu test
// bilerek kırılır).
function turkishLower(text: string): string {
  return text.replace(/İ|I/g, "i").toLowerCase().replace(/ı/g, "i");
}
function compact(text: string): string {
  return text.replace(/\s+/g, " ").trim();
}
function tokenizeJs(text: string): string[] {
  return turkishLower(compact(text))
    .replace(/[^a-z0-9çğıöşü_\s.-]/gi, " ")
    .split(/\s+/)
    .filter((token) => token.length >= 2)
    .slice(0, 80);
}
function overlapJs(query: string, text: string): number {
  const haystack = turkishLower(compact(text));
  const tokens = tokenizeJs(query);
  const overlap = tokens.reduce((count, token) => count + (haystack.includes(token) ? 1 : 0), 0);
  const exactBonus = haystack.includes(turkishLower(compact(query))) ? 4 : 0;
  return exactBonus + overlap * 2;
}

const CASES: Array<{ query: string; docs: string[] }> = [
  {
    query: "İngilizce öğrenme hedefi",
    docs: [
      "kullanıcı İngilizce öğrenme hedefi üzerinde çalışıyor",
      "tamamen alakasız yemek tarifi",
      "ingilizce kursu araştırıyor",
      "ISPARTA gezisi planı",
    ],
  },
  {
    query: "python backend api",
    docs: ["Python ile backend API geliştirme", "frontend css düzeni", ""],
  },
  {
    query: "kahve tercihi",
    docs: ["kullanıcı sade kahve seviyor, şekersiz", "çay tercih ediyor"],
  },
];

test("overlap_batch: C daemon skorları JS fallback ile birebir aynı", async (t) => {
  if (!existsSync(BIN)) {
    t.skip("elyan_nlp binary yok — compile:nlp çalıştırılmamış");
    return;
  }
  const daemon = new NlpDaemon(BIN);
  daemon.start();
  await new Promise((resolve) => setTimeout(resolve, 150));
  if (!daemon.isAvailable()) {
    t.skip("daemon başlamadı");
    return;
  }
  try {
    for (const { query, docs } of CASES) {
      const native = await daemon.overlapBatch(query, docs);
      assert.ok(native, "daemon skor dönmedi");
      const js = docs.map((doc) => overlapJs(query, doc));
      assert.deepEqual(native, js, `parity bozuk: query="${query}" native=${native} js=${js}`);
    }
  } finally {
    daemon.stop();
  }
});

test("overlap_batch: boş docs boş skor döner", async (t) => {
  if (!existsSync(BIN)) {
    t.skip("binary yok");
    return;
  }
  const daemon = new NlpDaemon(BIN);
  daemon.start();
  await new Promise((resolve) => setTimeout(resolve, 150));
  try {
    const scores = await daemon.overlapBatch("soru", []);
    assert.deepEqual(scores, []);
  } finally {
    daemon.stop();
  }
});
