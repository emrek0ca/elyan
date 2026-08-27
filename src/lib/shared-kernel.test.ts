import assert from "node:assert/strict";
import test from "node:test";
import { readdirSync, readFileSync, statSync } from "node:fs";
import { join } from "node:path";
import {
  asRecord,
  asRecordOrEmpty,
  recordArray,
  recordBoolean,
  recordNumber,
  recordString,
  recordStringList,
} from "./record.js";
import {
  asFiniteNumber,
  asNonEmptyString,
  collapseWhitespace,
  trimOnly,
  truncateText,
} from "./text.js";
import { isSideEffectTurn } from "../core/understanding/turn-facts.js";

/**
 * ORTAK ÇEKİRDEĞİN KORUMASI.
 *
 * Yüzden fazla kopya yardımcı fonksiyon tek modüle indirildi. Bu test onların
 * geri birikmesini engelliyor. Tekrarın kendisi zararsız görünür; zararlı olan,
 * kopyaların birbirinden bağımsız DEĞİŞEBİLMESİDİR — `compactText` adı altında
 * beş ayrı davranış tam olarak böyle birikti.
 *
 * Yeni bir kopya eklemek gerekiyorsa doğru hamle bu testi gevşetmek değil,
 * çekirdeğe DÜRÜST ADLA yeni bir fonksiyon eklemektir.
 */

const KERNEL_NAMES = [
  "readRecord",
  "asRecord",
  "readString",
  "readNumber",
  "readBoolean",
  "readArray",
  "readStringList",
  "readStringArray",
  "readMetadataString",
  "readMetadataNumber",
] as const;

/** Çekirdek modüllerin kendisi ve testler doğal olarak muaf. */
const EXEMPT_FILES = new Set(["src/lib/record.ts", "src/lib/text.ts"]);

/**
 * Kabul edilen kalıntılar: gövdesi çekirdekten GERÇEKTEN farklı olan,
 * yakınsaması ayrı bir karar gerektiren yerel yardımcılar. Liste büyümemeli;
 * her satır bir borçtur.
 */
const ACCEPTED_LOCAL_VARIANTS = 26;

function sourceFiles(dir: string, out: string[] = []): string[] {
  for (const entry of readdirSync(dir)) {
    const full = join(dir, entry);
    if (statSync(full).isDirectory()) {
      sourceFiles(full, out);
    } else if (entry.endsWith(".ts") && !entry.endsWith(".test.ts")) {
      out.push(full);
    }
  }
  return out;
}

test("kernel helpers are not re-implemented across the codebase", () => {
  const found: string[] = [];
  for (const file of sourceFiles("src")) {
    if (EXEMPT_FILES.has(file)) continue;
    const source = readFileSync(file, "utf8");
    for (const name of KERNEL_NAMES) {
      const pattern = new RegExp(`^function ${name}\\(`, "gm");
      const hits = source.match(pattern);
      if (hits) found.push(...hits.map(() => `${file}:${name}`));
    }
  }

  assert.ok(
    found.length <= ACCEPTED_LOCAL_VARIANTS,
    `Yerel kopya sayısı ${found.length}, izin verilen ${ACCEPTED_LOCAL_VARIANTS}. ` +
      `Yeni kopya eklemek yerine src/lib/record.ts veya src/lib/text.ts içine ` +
      `dürüst adlı bir fonksiyon ekle.\n${found.join("\n")}`,
  );
});

test("collapseWhitespace and trimOnly are genuinely different, and both are needed", () => {
  // Bu ayrım kaybolursa ortak çekirdeğin varlık sebebi de kaybolur:
  // kırk iki kopyanın dördü boşluk SIKIŞTIRMIYORDU ve o davranış korunmalı.
  assert.equal(collapseWhitespace("a   b\n c "), "a b c");
  assert.equal(trimOnly("a   b\n c "), "a   b\n c");

  // Metin olmayan girdi ikisinde de patlamaz.
  assert.equal(collapseWhitespace(null), "");
  assert.equal(collapseWhitespace(undefined), "");
  assert.equal(trimOnly(null), "");
  assert.equal(trimOnly(42), "");
});

test("truncateText keeps short text intact and marks what it cuts", () => {
  assert.equal(truncateText("kısa", 40), "kısa");
  assert.equal(truncateText("a".repeat(50), 10), `${"a".repeat(9)}…`);
  assert.equal(truncateText("  boşluklu   metin ", 40), "boşluklu metin");
  assert.equal(truncateText("herhangi", 0), "");
});

test("asRecord distinguishes absence, asRecordOrEmpty does not", () => {
  assert.equal(asRecord(null), null);
  assert.equal(asRecord([1, 2]), null, "dizi bir kayıt değildir");
  assert.equal(asRecord("metin"), null);
  assert.deepEqual(asRecord({ a: 1 }), { a: 1 });

  assert.deepEqual(asRecordOrEmpty(null), {});
  assert.deepEqual(asRecordOrEmpty([1, 2]), {});
  assert.deepEqual(asRecordOrEmpty({ a: 1 }), { a: 1 });
});

test("record readers treat a missing field and a wrong type the same way", () => {
  const record = {
    text: "  değer  ",
    blank: "   ",
    count: 7,
    notFinite: Number.NaN,
    flagTrue: true,
    flagFalse: false,
    list: ["a", "  b  ", "", 3],
    notList: "x",
  };

  assert.equal(recordString(record, "text"), "değer");
  assert.equal(recordString(record, "blank"), null, "boş metin yokluktur");
  assert.equal(recordString(record, "eksik"), null);
  assert.equal(recordString(null, "text"), null);

  assert.equal(recordNumber(record, "count"), 7);
  assert.equal(recordNumber(record, "notFinite"), null);
  assert.equal(recordNumber(record, "eksik"), null);

  // `false` ile "alan yok" AYNI ŞEY DEĞİLDİR; birçok kapı bu ayrıma dayanıyor.
  assert.equal(recordBoolean(record, "flagTrue"), true);
  assert.equal(recordBoolean(record, "flagFalse"), false);
  assert.equal(recordBoolean(record, "eksik"), null);

  assert.deepEqual(recordArray(record, "list"), ["a", "  b  ", "", 3]);
  assert.deepEqual(recordArray(record, "notList"), []);
  assert.deepEqual(recordStringList(record, "list"), ["a", "b"]);
});

test("value readers mirror the record readers", () => {
  assert.equal(asNonEmptyString("  x  "), "x");
  assert.equal(asNonEmptyString("   "), null);
  assert.equal(asNonEmptyString(5), null);
  assert.equal(asFiniteNumber(3.5), 3.5);
  assert.equal(asFiniteNumber(Number.POSITIVE_INFINITY), null);
  assert.equal(asFiniteNumber("3"), null, "metin sayı değildir");
});

test("a turn's side-effect answer does not depend on which module asks", () => {
  // ÖLÇÜLEN SAPMA: aynı soru yedi yerde soruluyor ve 1, 2 ya da 3 kaynağa
  // bakılıyordu. Yalnız onay isteyen bir tur `inference.ts`e göre yan
  // etkiliyken `desktop-work-order.ts`e göre değildi.
  const approvalOnly = { routeDecision: { requiresApproval: true } };
  const privacyOnly = { routeDecision: { privacyClass: "side_effect" } };
  const envelopeOnly = {
    understandingEnvelope: { risk: { side_effect: true } },
  };

  for (const sources of [approvalOnly, privacyOnly, envelopeOnly]) {
    assert.equal(isSideEffectTurn(sources), true, JSON.stringify(sources));
  }

  // Hiçbir kaynak işaret etmiyorsa tur yan etkili değildir.
  assert.equal(isSideEffectTurn({}), false);
  assert.equal(
    isSideEffectTurn({
      routeDecision: { privacyClass: "public", requiresApproval: false },
      understandingEnvelope: { risk: { side_effect: false } },
    }),
    false,
  );
});
