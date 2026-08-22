import { trStemPattern } from "../../lib/tr-word-boundary.js";
import {
  DESKTOP_CAPABILITY_MANIFEST,
  type DesktopCapabilityManifestEntry,
} from "./desktop-capability-manifest.js";
import {
  actionPolarityAdjustment,
  capabilitySafetyAdjustment,
  resolveQueryActionPolarity,
} from "./capability-action-polarity.js";

export type DesktopCapabilitySideEffectClass =
  | "none"
  | "read"
  | "write"
  | "destructive";

export type DesktopCapabilityOntologyEntry = {
  canonicalId: string;
  aliases: string[];
  examples: string[];
  negativeExamples: string[];
  privacyClass: string;
  sideEffectClass: DesktopCapabilitySideEffectClass;
  requiresApproval: boolean;
  runtimeNames: string[];
  manifest: DesktopCapabilityManifestEntry;
};

export type DesktopCapabilitySemanticMatch = {
  capability: string;
  score: number;
  entry: DesktopCapabilityOntologyEntry;
};

type SparseEmbedding = Map<number, number>;

// 512 kova, 81 yetenek × yüzlerce karakter-ngramı için çok dardı: farklı
// özellikler aynı kovaya düşüp skoru gürültüye çeviriyordu ("şu şarkıyı çal"
// → desktop_os.status). Ölçüm bunu gösterdi; kova sayısı çarpışmayı pratikte
// ortadan kaldıracak seviyeye çekildi.
const EMBEDDING_BUCKETS = 16_384;
const ontologyCache = new Map<string, DesktopCapabilityOntologyEntry[]>();
const embeddingCache = new Map<string, SparseEmbedding>();

/**
 * Kanonik normalleştirici. Eylem kutupluluğu katmanı da BUNU kullanır —
 * ikinci bir normalleştirme kuralı seti, iki katmanın sessizce ayrışması
 * demektir.
 */
export function normalizeText(value: string): string {
  return value
    .toLocaleLowerCase("tr-TR")
    // NFKD does not decompose Turkish dotless ı; keep the canonical token
    // space consistent with the ASCII capability/action dictionaries.
    .replaceAll("ı", "i")
    .normalize("NFKD")
    .replace(/\p{Diacritic}/gu, "")
    .replace(/[_./-]+/g, " ")
    .replace(/[^\p{L}\p{N}\s]+/gu, " ")
    .replace(/\s+/g, " ")
    .trim();
}

function hashToken(value: string): number {
  let hash = 2166136261;
  for (let index = 0; index < value.length; index += 1) {
    hash ^= value.charCodeAt(index);
    hash = Math.imul(hash, 16777619);
  }
  return (hash >>> 0) % EMBEDDING_BUCKETS;
}

function addFeature(vector: SparseEmbedding, feature: string, weight: number) {
  const bucket = hashToken(feature);
  vector.set(bucket, (vector.get(bucket) ?? 0) + weight);
}

// Turkish case/number suffixes are kept as secondary features. The original
// token remains authoritative, while a conservative stem feature lets
// `whatsapptan`, `safariyi`, `raporu` and `sekmeye` meet their catalog forms.
// This is morphology support, not a second routing dictionary; notably
// `belgesel` has no removable suffix here and does not collapse to `belge`.
const INFLECTION_SUFFIXES = [
  "lardan", "lerden", "lerinin",
  "ndan", "nden", "tan", "ten", "dan", "den", "nin", "nun",
  "leri", "lari", "ler", "lar", "yi", "yu", "ye", "ya",
];

function stemVariants(token: string): string[] {
  const variants: string[] = [];
  for (const suffix of INFLECTION_SUFFIXES) {
    if (!token.endsWith(suffix)) continue;
    const stem = token.slice(0, -suffix.length);
    if (stem.length >= 4) variants.push(stem);
  }
  return [...new Set(variants)];
}

function embedText(value: string): SparseEmbedding {
  const normalized = normalizeText(value);
  const cached = embeddingCache.get(normalized);
  if (cached) return cached;
  const vector: SparseEmbedding = new Map();
  const tokens = normalized.split(" ").filter(Boolean);
  for (const token of tokens) {
    addFeature(vector, `w:${token}`, 1);
    for (let size = 3; size <= 5; size += 1) {
      for (let index = 0; index + size <= token.length; index += 1) {
        addFeature(vector, `c:${token.slice(index, index + size)}`, 0.18);
      }
    }
    for (const stem of stemVariants(token)) {
      addFeature(vector, `s:${stem}`, 0.72);
      for (let size = 3; size <= 5; size += 1) {
        for (let index = 0; index + size <= stem.length; index += 1) {
          addFeature(vector, `sc:${stem.slice(index, index + size)}`, 0.1);
        }
      }
    }
  }
  for (let index = 0; index + 1 < tokens.length; index += 1) {
    addFeature(vector, `b:${tokens[index]} ${tokens[index + 1]}`, 0.65);
  }
  embeddingCache.set(normalized, vector);
  return vector;
}

function cosine(left: SparseEmbedding, right: SparseEmbedding): number {
  let dot = 0;
  let leftNorm = 0;
  let rightNorm = 0;
  for (const value of left.values()) leftNorm += value * value;
  for (const value of right.values()) rightNorm += value * value;
  for (const [bucket, value] of left.entries()) {
    dot += value * (right.get(bucket) ?? 0);
  }
  if (leftNorm <= 0 || rightNorm <= 0) return 0;
  return dot / (Math.sqrt(leftNorm) * Math.sqrt(rightNorm));
}

/**
 * TÜRKÇE KÖK + EK TOLERANSI — `\b` burada sessizce ölüyordu.
 *
 * Ölçülen arıza (2026-08-22): `make_directory` yan etki sınıfı "none" çıkıyordu.
 * Açıklaması "Klasör OLUŞTURUR" — yazma kalıbı `\bolustur\b` idi ve Türkçe
 * ek yüzünden ("olusturur") EŞLEŞMİYORDU. Yani klasör oluşturmak "yan etkisiz"
 * sayılıyordu; hem yönlendirmedeki yan-etki uyumu hem de plan sonuç-kapsamı
 * bu yanlış sınıfı okuyordu.
 *
 * Bu, bu projenin en sık tekrarlayan hata sınıfı (`\büret\b` de aynı şekilde
 * ölmüştü). Doğru araç sınır değil, SINIRLI EK TOLERANSI: `trStemPattern`.
 * İngilizce kökler `\b` ile kalır — orada sorun yok.
 */
const DESTRUCTIVE_PATTERN = new RegExp(
  `\\b(?:delete|remove|erase|destructive)\\b|${trStemPattern(["sil", "kaldir"]).source}`,
  "u",
);
const READ_PATTERN = new RegExp(
  `\\b(?:read|search|list|status|observe|analyze)\\b|${trStemPattern([
    "oku",
    "ara",
    "listele",
    "gozlemle",
    "analiz",
  ]).source}`,
  "u",
);
const WRITE_PATTERN = new RegExp(
  `\\b(?:write|send|add|save|move|patch|commit|create|update|edit)\\b|${trStemPattern([
    "yaz",
    "gonder",
    "ekle",
    "kaydet",
    "tasi",
    "olustur",
    "duzenle",
    "hazirla",
  ]).source}`,
  "u",
);

function sideEffectClassFor(
  entry: DesktopCapabilityManifestEntry,
): DesktopCapabilitySideEffectClass {
  const name = entry.name.toLocaleLowerCase("en-US");
  const text = normalizeText(
    [
      entry.name,
      entry.displayName,
      entry.description,
      entry.usage,
      entry.privacyClass,
    ].join(" "),
  );
  if (
    DESTRUCTIVE_PATTERN.test(text) ||
    name.includes("delete")
  ) {
    return "destructive";
  }
  if (
    entry.privacyClass.includes("_read") ||
    entry.privacyClass.includes("screen") ||
    READ_PATTERN.test(text)
  ) {
    return "read";
  }
  if (entry.privacyClass.includes("_write") || WRITE_PATTERN.test(text)) {
    return "write";
  }
  return "none";
}

function runtimeNamesFor(name: string): string[] {
  const dotted = name.replaceAll("_", ".");
  const underscored = name.replaceAll(".", "_");
  return [...new Set([name, dotted, underscored])];
}

// fewShots örnekleri `{"args": {"app_name": "Spotify"}}` biçiminde. Tümünü
// JSON olarak gömmek "args"/"app name" gibi hiçbir niyet taşımayan token'ları
// her girdiye dağıtıyordu. Yalnız yaprak değerleri alıyoruz.
function leafStringValues(value: unknown, depth = 0): string[] {
  if (depth > 4) return [];
  if (typeof value === "string") return value.trim() ? [value] : [];
  if (typeof value === "number" || typeof value === "boolean") return [];
  if (Array.isArray(value)) {
    return value.flatMap((item) => leafStringValues(item, depth + 1));
  }
  if (value && typeof value === "object") {
    return Object.values(value).flatMap((item) =>
      leafStringValues(item, depth + 1),
    );
  }
  return [];
}

function examplesFromFewShots(
  fewShots: DesktopCapabilityManifestEntry["fewShots"],
): string[] {
  return fewShots.flatMap((shot) => leafStringValues(shot)).slice(0, 6);
}

export function getDesktopCapabilityOntology(): DesktopCapabilityOntologyEntry[] {
  const cached = ontologyCache.get("v1");
  if (cached) return cached;
  const entries = DESKTOP_CAPABILITY_MANIFEST.map((entry) => {
    // Takma adlar ve karşı-örnekler TEK kaynaktan gelir: masaüstündeki
    // capability_phrasebook, manifest üzerinden. Burada eskiden ~20 yeteneği
    // kapsayan elle tutulan bir kopya vardı (CURATED_ALIASES/NEGATIVES); iki
    // liste kaçınılmaz olarak sürükleniyordu. İçeriği kaynağa taşındı ve
    // kopya silindi.
    const aliases = [
      entry.name,
      entry.displayName,
      ...runtimeNamesFor(entry.name),
      ...entry.utterances,
      ...entry.skillAffinity,
    ];
    // verificationPlan / liveNarration bilinçli olarak dışarıda: 81 girdinin
    // tamamında birebir aynı İngilizce kalıp ("Structured result must return
    // ok=true…"). Ayırt edici değeri sıfır, blob'u şişirip sinyali seyreltiyor.
    const examples = [
      entry.description,
      entry.usage,
      ...entry.whenToUse,
      ...examplesFromFewShots(entry.fewShots),
    ];
    const negativeExamples = [...entry.whenNotToUse, ...entry.notFor];
    return {
      canonicalId: entry.name,
      aliases: [...new Set(aliases.map(normalizeText).filter(Boolean))],
      examples: [...new Set(examples.map(normalizeText).filter(Boolean))],
      negativeExamples: [
        ...new Set(negativeExamples.map(normalizeText).filter(Boolean)),
      ],
      privacyClass: entry.privacyClass,
      sideEffectClass: sideEffectClassFor(entry),
      requiresApproval: entry.requiresApproval,
      runtimeNames: runtimeNamesFor(entry.name),
      manifest: entry,
    };
  });
  ontologyCache.set("v1", entries);
  return entries;
}

// ── Skorlama indeksi ────────────────────────────────────────────────────
//
// Eski yaklaşım: girdinin bütün metnini tek bir blob'a birleştirip sorguyla
// kosinüs alıyordu. 3 kelimelik bir sorgu 43 kelimelik blob'a karşı ölçülünce
// ayırt edici sinyal blob'un kendi kütlesinde kayboluyordu.
//
// Yeni yaklaşım: her alan ayrı bir "kanıt belgesi" (probe). Skor, alanların
// ORTALAMASI değil EN İYİSİ. Bir yeteneği seçmek için tek bir güçlü kanıt
// yeter; on tane alakasız alan onu cezalandırmamalı.
type Probe = { vector: SparseEmbedding; weight: number };

type ScoringIndex = {
  idf: Map<number, number>;
  probes: Map<string, Probe[]>;
  negatives: Map<string, SparseEmbedding[]>;
};

let scoringIndexCache: ScoringIndex | null = null;

function rawProbeTexts(
  entry: DesktopCapabilityOntologyEntry,
): Array<{ text: string; weight: number }> {
  const probes: Array<{ text: string; weight: number }> = [];
  // Ağırlıklar, kanıtın niyet taşıma gücüne göre: takma ad doğrudan kullanıcı
  // ifadesidir, açıklama ikinci elden anlatımdır.
  for (const alias of entry.aliases) probes.push({ text: alias, weight: 1 });
  for (const example of entry.examples) probes.push({ text: example, weight: 0.88 });
  return probes.filter((probe) => probe.text.length > 0);
}

function applyIdf(
  vector: SparseEmbedding,
  idf: Map<number, number>,
): SparseEmbedding {
  const weighted: SparseEmbedding = new Map();
  for (const [bucket, value] of vector.entries()) {
    weighted.set(bucket, value * (idf.get(bucket) ?? 1));
  }
  return weighted;
}

function getScoringIndex(): ScoringIndex {
  if (scoringIndexCache) return scoringIndexCache;
  const ontology = getDesktopCapabilityOntology();

  // IDF girdi düzeyinde: bir özellik kaç FARKLI yetenekte geçiyor. Her
  // girdide geçen "kullan/dosya/aç" gibi özellikler ayırt edici değildir ve
  // bastırılır; yalnız bir yetenekte geçenler öne çıkar.
  const documentFrequency = new Map<number, number>();
  const rawByCapability = new Map<
    string,
    Array<{ vector: SparseEmbedding; weight: number }>
  >();
  for (const entry of ontology) {
    const vectors = rawProbeTexts(entry).map((probe) => ({
      vector: embedText(probe.text),
      weight: probe.weight,
    }));
    rawByCapability.set(entry.canonicalId, vectors);
    const seen = new Set<number>();
    for (const probe of vectors) {
      for (const bucket of probe.vector.keys()) seen.add(bucket);
    }
    for (const bucket of seen) {
      documentFrequency.set(bucket, (documentFrequency.get(bucket) ?? 0) + 1);
    }
  }

  const total = Math.max(1, ontology.length);
  const idf = new Map<number, number>();
  for (const [bucket, frequency] of documentFrequency.entries()) {
    idf.set(bucket, Math.log(1 + total / (1 + frequency)));
  }

  const probes = new Map<string, Probe[]>();
  const negatives = new Map<string, SparseEmbedding[]>();
  for (const entry of ontology) {
    probes.set(
      entry.canonicalId,
      (rawByCapability.get(entry.canonicalId) ?? []).map((probe) => ({
        vector: applyIdf(probe.vector, idf),
        weight: probe.weight,
      })),
    );
    negatives.set(
      entry.canonicalId,
      entry.negativeExamples.map((example) =>
        applyIdf(embedText(example), idf),
      ),
    );
  }

  scoringIndexCache = { idf, probes, negatives };
  return scoringIndexCache;
}

function sideEffectCompatible(
  requested: DesktopCapabilitySideEffectClass | null | undefined,
  candidate: DesktopCapabilitySideEffectClass,
): boolean {
  if (!requested || requested === "none") return true;
  if (requested === "read") return candidate === "read" || candidate === "none";
  if (requested === "write") return candidate === "write";
  return candidate === "destructive";
}

export function matchDesktopCapabilitiesSemantically(input: {
  query: string;
  hints?: string[];
  intent?: string | null;
  sideEffectLevel?: DesktopCapabilitySideEffectClass | null;
  limit?: number;
  threshold?: number;
}): DesktopCapabilitySemanticMatch[] {
  const query = normalizeText([input.query, ...(input.hints ?? [])].join(" "));
  if (!query) return [];
  const index = getScoringIndex();
  const queryEmbedding = applyIdf(embedText(query), index.idf);
  const intent = input.intent ?? "";
  // Eylem kutbu YAPISAL bir boyut, kelime torbasında bir özellik değil.
  // Torbada "aç" (2 harf, 0 n-gram) nesne adının yanında eziliyor ve
  // "Chrome'u aç" top-1'de `close_app` üretiyordu. Bkz.
  // `capability-action-polarity.ts`.
  const queryPolarity = resolveQueryActionPolarity(query);
  const matches = getDesktopCapabilityOntology()
    .map((entry) => {
      let positive = 0;
      for (const probe of index.probes.get(entry.canonicalId) ?? []) {
        const score = cosine(queryEmbedding, probe.vector) * probe.weight;
        if (score > positive) positive = score;
      }
      let negative = 0;
      for (const example of index.negatives.get(entry.canonicalId) ?? []) {
        const score = cosine(queryEmbedding, example);
        if (score > negative) negative = score;
      }
      const intentBoost =
        intent === "browser_workflow" && entry.canonicalId === "browser_control"
          ? 0.22
          : intent === "browser_workflow" && entry.canonicalId.includes("browser")
            ? 0.08
          : intent === "screen_action" &&
              (entry.canonicalId.startsWith("desktop_operator") ||
                entry.canonicalId.includes("screen") ||
                entry.canonicalId.includes("active_window"))
            ? 0.12
            : intent === "document_workflow" && entry.canonicalId === "document_write"
              ? 0.22
              : intent === "document_workflow" &&
                  (entry.canonicalId.includes("document") ||
                    entry.canonicalId.includes("spreadsheet") ||
                    entry.canonicalId.includes("presentation"))
                ? 0.1
              : intent === "file_workflow" && entry.canonicalId.includes("file")
                ? 0.1
                : 0;
      const sideEffectPenalty = sideEffectCompatible(
        input.sideEffectLevel,
        entry.sideEffectClass,
      )
        ? 0
        : 0.18;
      const polarityAdjustment = actionPolarityAdjustment({
        queryPolarity,
        capabilityId: entry.canonicalId,
      });
      const safetyAdjustment = capabilitySafetyAdjustment({
        normalizedQuery: query,
        capabilityId: entry.canonicalId,
      });
      return {
        capability: entry.canonicalId,
        score: Number(
          Math.max(
            0,
            positive +
              intentBoost +
              polarityAdjustment +
              safetyAdjustment -
              negative * 0.5 -
              sideEffectPenalty,
          ).toFixed(4),
        ),
        entry,
      };
    })
    .filter((match) => match.score >= (input.threshold ?? 0.18))
    .sort((left, right) => right.score - left.score || left.capability.localeCompare(right.capability));
  return matches.slice(0, input.limit ?? 8);
}
