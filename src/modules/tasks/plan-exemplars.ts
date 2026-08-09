import { and, desc, eq, isNotNull } from "drizzle-orm";
import type { FastifyInstance } from "fastify";
import { tasks } from "../../db/schema.js";
import {
  embedQueryForStorage,
  embedTextsForStorage,
} from "../brain/semantic-embedder.js";

/**
 * Gerçek sonuçlardan öğrenen örnek havuzu.
 *
 * Planlayıcıya elle yazılmış few-shot vermek bir yere kadar gider: örnekler
 * donuktur, gerçek kullanımı takip etmez. Oysa sistem her başarılı görevde
 * zaten etiketli veri üretiyor — istek + yürütülen plan + doğrulanmış sonuç.
 * Bu veri bedava ve kullanıcının kendi diliyle yazılmış.
 *
 * Burada yeni istek, kullanıcının GEÇMİŞ BAŞARILI işleriyle vektör
 * benzerliğine göre eşleştirilir ve en yakın birkaçı planlama istemine örnek
 * olarak konur. Sistem kullanıldıkça kendi kendine iyileşir; yeni bir ifade
 * biçimi bir kez doğru çalıştığında ikinci kez sorulduğunda örnek olarak
 * geri gelir.
 *
 * GİZLİLİK — bu modülün en önemli kuralı
 * --------------------------------------
 * Örnekler YALNIZ isteği yapan kullanıcının kendi geçmişinden gelir.
 * `userId` zorunlu parametredir ve sorguya doğrudan girer; varsayılanı,
 * "hepsi" seçeneği ya da kullanıcılar arası bir havuz YOKTUR. Başka bir
 * kullanıcının isteği hiçbir koşulda bir başkasının istemine giremez.
 */

const CANDIDATE_LIMIT = 60;
const EXEMPLAR_LIMIT = 3;
const MIN_SIMILARITY = 0.82;
const EXEMPLAR_CACHE_SCOPE = "desktop_plan_exemplars_v1";
const EMBED_TIMEOUT_MS = 3_000;

export type PlanExemplar = {
  prompt: string;
  capabilities: string[];
  similarity: number;
};

function readRecord(value: unknown): Record<string, unknown> | null {
  return value && typeof value === "object" && !Array.isArray(value)
    ? (value as Record<string, unknown>)
    : null;
}

function readCapabilitySequence(payload: unknown): string[] {
  const record = readRecord(payload);
  const preview = readRecord(record?.planPreview);
  const steps = preview?.steps;
  if (!Array.isArray(steps)) return [];
  const sequence: string[] = [];
  for (const step of steps.slice(0, 8)) {
    const capability = readRecord(step)?.capability;
    if (typeof capability === "string" && capability.trim()) {
      sequence.push(capability.trim());
    }
  }
  return sequence;
}

function readPrompt(payload: unknown): string {
  const record = readRecord(payload);
  const prompt = record?.prompt;
  if (typeof prompt !== "string") return "";
  // Uzun istemler hem gömme kalitesini düşürür hem istemi şişirir; ilk cümle
  // öbeği niyeti zaten taşır.
  return prompt.replace(/\s+/g, " ").trim().slice(0, 240);
}

/**
 * Kullanıcının kendi geçmişindeki başarılı masaüstü planlarını toplar.
 *
 * `payloadBlobId` taşıyan (yani gövdesi blob'a taşınmış) kayıtlar atlanır:
 * örnek toplamak için blob okumak istek yolunu yavaşlatır ve kazanç küçüktür.
 */
async function collectCandidates(
  app: FastifyInstance,
  userId: string,
): Promise<Array<{ prompt: string; capabilities: string[] }>> {
  const rows = await app.db
    .select({ payload: tasks.payload })
    .from(tasks)
    .where(
      and(
        eq(tasks.userId, userId),
        eq(tasks.status, "completed"),
        isNotNull(tasks.completedAt),
      ),
    )
    .orderBy(desc(tasks.completedAt))
    .limit(CANDIDATE_LIMIT);

  const seen = new Set<string>();
  const candidates: Array<{ prompt: string; capabilities: string[] }> = [];
  for (const row of rows) {
    const prompt = readPrompt(row.payload);
    const capabilities = readCapabilitySequence(row.payload);
    if (!prompt || capabilities.length === 0) continue;
    const key = `${prompt}::${capabilities.join(">")}`;
    if (seen.has(key)) continue;
    seen.add(key);
    candidates.push({ prompt, capabilities });
  }
  return candidates;
}

function dot(left: number[], right: number[]): number {
  let sum = 0;
  for (let index = 0; index < left.length; index += 1) {
    sum += left[index] * right[index];
  }
  return sum;
}

/**
 * Yeni isteğe en yakın geçmiş çözümleri döndürür.
 *
 * Embedder ya da geçmiş yoksa boş dizi döner; planlama bundan etkilenmez.
 */
export async function selectPlanExemplars(
  app: FastifyInstance,
  input: { userId: string; query: string; limit?: number },
): Promise<PlanExemplar[]> {
  const userId = String(input.userId ?? "").trim();
  const query = String(input.query ?? "").replace(/\s+/g, " ").trim();
  // Gizlilik kapısı: kullanıcı kimliği olmadan örnek toplanmaz. Bu erken
  // dönüş bir optimizasyon değil, sözleşmenin kendisidir.
  if (!userId || !query) return [];

  const candidates = await collectCandidates(app, userId).catch(() => []);
  if (candidates.length === 0) return [];

  const [queryVector, candidateVectors] = await Promise.all([
    embedQueryForStorage(query, app.log, EXEMPLAR_CACHE_SCOPE, EMBED_TIMEOUT_MS),
    embedTextsForStorage(
      candidates.map((candidate) => candidate.prompt),
      app.log,
      EXEMPLAR_CACHE_SCOPE,
      EMBED_TIMEOUT_MS,
    ),
  ]);
  if (!queryVector || !candidateVectors) return [];

  const scored = candidates.map((candidate, index) => ({
    prompt: candidate.prompt,
    capabilities: candidate.capabilities,
    similarity: Number(dot(queryVector, candidateVectors[index]).toFixed(4)),
  }));

  return scored
    .filter((item) => item.similarity >= MIN_SIMILARITY)
    // Aynı isteğin birebir tekrarı örnek olarak işe yaramaz; kendi kendini
    // kopyalamak planlayıcıya yeni bilgi vermez.
    .filter((item) => item.prompt.toLocaleLowerCase("tr-TR") !== query.toLocaleLowerCase("tr-TR"))
    .sort((left, right) => right.similarity - left.similarity)
    .slice(0, input.limit ?? EXEMPLAR_LIMIT);
}

/** Planlama istemine girecek metni üretir; örnek yoksa boş string. */
export function renderPlanExemplars(exemplars: PlanExemplar[]): string {
  if (exemplars.length === 0) return "";
  const lines = exemplars.map(
    (exemplar) => `- "${exemplar.prompt}" → ${exemplar.capabilities.join(" → ")}`,
  );
  return [
    "PREVIOUSLY SUCCESSFUL PLANS FOR THIS SAME USER (their own history; similar requests and the capability chain that actually worked).",
    "Treat these as evidence of what this user means by such wording, not as a template to copy blindly:",
    ...lines,
  ].join("\n");
}
