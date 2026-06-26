import { buildHashedKnowledgeEmbedding } from "../../modules/brain/retrieval.js";
import type { UnderstandingIntent } from "./types.js";

/**
 * Semantic fallback for the regex intent classifier.
 *
 * The rule-based classifier in `intent-classifier.ts` is fast and precise for
 * known phrasings, but it loses the intent entirely when a prompt is paraphrased
 * in a way no pattern anticipated (it then falls back to "chat"/"unknown"). This
 * module fills that gap: each classifiable intent has a small set of seed phrases
 * whose hashed embeddings are averaged into a prototype vector at module load.
 * A prompt is then assigned the nearest prototype by cosine similarity.
 *
 * It reuses the exact same hashed-embedding algorithm the C NLP core mirrors
 * (`buildHashedKnowledgeEmbedding` ↔ C `embed_256`), so the math is consistent
 * across the stack and stays cheap (no model, fully synchronous). The embedding
 * compute is only paid on the rare no-regex-match path.
 */

const INTENT_SEED_PHRASES: Partial<Record<UnderstandingIntent, string[]>> = {
  coding: [
    "bu fonksiyonu refactor et",
    "typescript ile bir api yaz",
    "şu kodu implemente et",
    "write a python function for this",
    "add a unit test for this module",
  ],
  debugging: [
    "kod çalışmıyor hata veriyor",
    "bu exception'ı düzelt",
    "uygulama crash oluyor neden",
    "fix this failing build",
    "why does this throw a stack trace",
  ],
  research: [
    "bunu araştır ve kaynak göster",
    "güncel verilerle karşılaştır",
    "en son gelişmeleri incele",
    "find sources and cite them",
    "verify these facts online",
  ],
  writing: [
    "bu metni düzenle ve akıcı yap",
    "bir mail taslağı yaz",
    "şunu profesyonelce özetle",
    "rewrite this paragraph politely",
    "proofread and fix the grammar",
  ],
  math: [
    "bu denklemi çöz",
    "integralini hesapla",
    "şu problemi adım adım çöz",
    "solve this equation",
    "compute the derivative",
  ],
  document: [
    "bu pdf'i oku ve özetle",
    "belgenin içinde ne yazıyor",
    "excel tablosunu dışa aktar",
    "extract the text from this document",
    "convert this file to docx",
  ],
  image: [
    "bu görseli analiz et",
    "fotoğraftan metni çıkar",
    "bir resim oluştur",
    "describe what is in this photo",
    "generate an image of a landscape",
  ],
  automation: [
    "bunu her sabah otomatik çalıştır",
    "bir iş akışı kur",
    "şu görevi zamanla ve tetikle",
    "automate this workflow",
    "schedule a recurring task",
  ],
  browser: [
    "şu siteyi aç ve gez",
    "web sayfasından veri çek",
    "tarayıcıda bu butona tıkla",
    "navigate to this website",
    "scrape this web page",
  ],
  computer: [
    "masaüstünde şu dosyayı aç",
    "ekran görüntüsü al",
    "bilgisayarda bir pencere aç",
    "take a screenshot of the desktop",
    "press a hotkey on my machine",
  ],
  planning: [
    "bir yol haritası çıkar",
    "bu projeyi adımlara böl",
    "stratejiyi ve mimariyi planla",
    "break this down into a roadmap",
    "design the system architecture",
  ],
};

function averagePrototype(phrases: string[]): number[] {
  const vectors = phrases.map((phrase) => buildHashedKnowledgeEmbedding(phrase));
  const dim = vectors[0]?.length ?? 0;
  const sum = new Array<number>(dim).fill(0);
  for (const vector of vectors) {
    for (let i = 0; i < dim; i += 1) {
      sum[i] += vector[i] ?? 0;
    }
  }
  const magnitude = Math.sqrt(sum.reduce((acc, value) => acc + value * value, 0));
  if (magnitude <= 0) {
    return sum;
  }
  return sum.map((value) => value / magnitude);
}

const INTENT_PROTOTYPES: Array<{ intent: UnderstandingIntent; vector: number[] }> = Object.entries(
  INTENT_SEED_PHRASES,
).map(([intent, phrases]) => ({
  intent: intent as UnderstandingIntent,
  vector: averagePrototype(phrases ?? []),
}));

function dot(a: number[], b: number[]): number {
  const n = Math.min(a.length, b.length);
  let sum = 0;
  for (let i = 0; i < n; i += 1) {
    sum += a[i] * b[i];
  }
  return sum;
}

/**
 * Returns the nearest intent prototype to `text` by cosine similarity, or null
 * when the text is empty or the best match is too weak to be meaningful.
 * Both the query and prototype vectors are L2-normalized, so the dot product is
 * the cosine similarity directly.
 */
export function classifyIntentSemantic(
  text: string,
  minScore = 0.18,
): { intent: UnderstandingIntent; score: number } | null {
  const trimmed = text.trim();
  if (trimmed.length === 0) {
    return null;
  }
  const queryVector = buildHashedKnowledgeEmbedding(trimmed);
  let best: { intent: UnderstandingIntent; score: number } | null = null;
  for (const prototype of INTENT_PROTOTYPES) {
    const score = dot(queryVector, prototype.vector);
    if (!best || score > best.score) {
      best = { intent: prototype.intent, score };
    }
  }
  if (!best || best.score < minScore) {
    return null;
  }
  return best;
}
