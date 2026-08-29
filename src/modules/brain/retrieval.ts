import { createHash } from "node:crypto";
import { and, desc, eq, ilike, or, sql } from "drizzle-orm";
import type { FastifyInstance } from "fastify";
import { knowledgeChunks, knowledgeDocuments, trainingJobs } from "../../db/schema.js";
import type { BrainScope } from "../../contracts/domain.js";
import { rerankSemanticCandidates } from "./semantic-rerank.js";
import {
  embedQueryForStorage,
  embedTextsForStorage,
  STORAGE_SEMANTIC_MODEL_TAG,
} from "./semantic-embedder.js";
import { nlpDaemon } from "../../lib/nlp-daemon.js";
import { contentTerms, stemTurkish } from "./lexical-turkish.js";
import { collapseWhitespace as compactText } from "../../lib/text.js";

const RETRIEVAL_VECTOR_DIMENSIONS = 256;
/**
 * Hash embedding sürümü — tokenleştirme değiştiğinde ARTAR.
 *
 * `v2`nin `v1`den tek farkı Türkçe kök bulmadır. Fark küçük görünür, sonucu
 * değildir: `v1` tam token hash'liyordu, bu yüzden "ilkeleri" ile "ilkeler"
 * FARKLI bucket'lara düşüyor ve aynı kavramı arayan sorgu ile indekslenen
 * metin birbirini bulamıyordu. Türkçe eklemeli bir dil olduğu için bu, her
 * çekim ekinde sessizce kaybedilen bir eşleşme demek.
 *
 * Sürüm ayrımı ŞART: eski satırlar `v1` bucket'larıyla yazıldı ve `v2` bir
 * sorguyla karşılaştırılamaz. `embedding_model` sütunu her satırın hangi
 * sözlükle yazıldığını söyler; yeniden indeksleme tamamlanana kadar ikisi bir
 * arada yaşar ve sorgu tarafı satırın kendi sürümüne göre okunur.
 */
export const RETRIEVAL_EMBEDDING_MODEL_V1 = "elyan_hash_v1";
export const RETRIEVAL_EMBEDDING_MODEL_V2 = "elyan_hash_v2";
export const RETRIEVAL_EMBEDDING_MODEL = RETRIEVAL_EMBEDDING_MODEL_V2;

const pgvectorAvailabilityCache = new WeakMap<FastifyInstance, Promise<boolean>>();
const embeddingColumnAvailabilityCache = new WeakMap<FastifyInstance, Promise<boolean>>();

export type RetrievalSearchResult = {
  documentId: string;
  chunkId: string;
  title: string;
  scope: BrainScope;
  sourceType: string;
  sourceUri: string | null;
  summary: string | null;
  content: string;
  tokenEstimate: number;
  ordinal: number;
  metadata: unknown;
  score: number;
  updatedAt: Date;
};

export type KnowledgeSearchScope = "visible" | "system_corpus";

function knowledgeVisibility(
  userId: string,
  scope: KnowledgeSearchScope | undefined,
) {
  return scope === "system_corpus"
    ? and(
        eq(knowledgeChunks.scope, "shared"),
        sql`${knowledgeDocuments.metadata}->>'elyanCorpusPurpose' = 'knowledge'`,
      )
    : or(
        eq(knowledgeChunks.scope, "shared"),
        eq(knowledgeChunks.ownerUserId, userId),
      );
}

/* Arama katmanı case-folding: i-ailesi tek harfe iner (İ/I/ı → i) — C daemon
 * tr_lower tablosuyla birebir. NOT: hashed embedding bucket'ları tokenlere
 * bağlı; ı içeren ESKİ kayıtlı vektörler bu tokenler için kısmen eşleşmez
 * (birincil sinyal embedding_v2/e5 olduğundan etki ikincil, yeni yazımlar
 * tutarlı). Eski davranış İ'li kelimelerde C↔JS arasında zaten tutarsızdı. */
function tokenize(text: string): string[] {
  return compactText(text)
    .replace(/İ|I/g, "i")
    .toLowerCase()
    .replace(/ı/g, "i")
    .replace(/[^a-z0-9çğıöşü_\s.-]/gi, " ")
    .split(/\s+/)
    .filter((token) => token.length >= 2)
    .slice(0, 120);
}

/**
 * `v2` tokenleştirme: aynı temizlik + Türkçe kök.
 *
 * Kök alma token SAYISINI artırmaz (token yerine kökü konur), bu yüzden
 * vektör yoğunluğu ve mevcut eşik davranışı aynı ölçekte kalır; değişen tek
 * şey, aynı kavramın çekimli yazımlarının artık AYNI bucket'a düşmesidir.
 */
function tokenizeV2(text: string): string[] {
  return tokenize(text).map((token) =>
    token.length >= 4 ? stemTurkish(token) : token,
  );
}

function hashTokenToBuckets(token: string): Array<{ index: number; sign: number }> {
  const digest = createHash("sha256").update(token).digest();
  const buckets: Array<{ index: number; sign: number }> = [];
  for (let offset = 0; offset < 6; offset += 2) {
    const bucket = ((digest[offset] << 8) | digest[offset + 1]) % RETRIEVAL_VECTOR_DIMENSIONS;
    const sign = digest[offset + 2] % 2 === 0 ? 1 : -1;
    buckets.push({ index: bucket, sign });
  }
  return buckets;
}

/**
 * VARSAYILAN `v1` OLMAK ZORUNDA.
 *
 * Bu fonksiyonu yalnız bilgi indeksi kullanmıyor: `intent-semantic.ts` de
 * sabit prototipleri karşılaştırırken çağırıyor ve oradaki eşikler v1
 * skorlarına göre ÖLÇÜLEREK kalibre edildi. Varsayılanı v2 yapmak, sürümleme
 * yapmanın amacını tersine çevirip ilgisiz bir sınıflandırıcının davranışını
 * sessizce değiştirdi ("ileri analiz dersinden örnek soru yaz" → math yerine
 * writing). Sürüm, isteyen çağıranın AÇIKÇA seçtiği bir şeydir.
 */
export function buildHashedKnowledgeEmbedding(
  text: string,
  modelTag: string = RETRIEVAL_EMBEDDING_MODEL_V1,
): number[] {
  const vector = new Array<number>(RETRIEVAL_VECTOR_DIMENSIONS).fill(0);
  const tokens =
    modelTag === RETRIEVAL_EMBEDDING_MODEL_V2 ? tokenizeV2(text) : tokenize(text);
  for (const token of tokens) {
    const weight = Math.min(2.5, 1 + token.length / 10);
    for (const bucket of hashTokenToBuckets(token)) {
      vector[bucket.index] += bucket.sign * weight;
    }
  }

  const magnitude = Math.sqrt(vector.reduce((sum, value) => sum + value * value, 0));
  if (magnitude <= 0) {
    return vector;
  }

  return vector.map((value) => Number((value / magnitude).toFixed(6)));
}

/** C-accelerated embedding; falls back to pure-JS when daemon unavailable */
async function buildEmbedding(text: string): Promise<number[]> {
  if (nlpDaemon.isAvailable()) {
    const vec = await nlpDaemon.embed256(text).catch(() => null);
    if (vec && vec.length === RETRIEVAL_VECTOR_DIMENSIONS) return vec;
  }
  // Bilgi indeksi sürümü AÇIKÇA seçilir: sorgu ile indeks aynı sözlüğü
  // kullanmak zorunda.
  return buildHashedKnowledgeEmbedding(text, RETRIEVAL_EMBEDDING_MODEL);
}

function vectorLiteral(vector: number[]): string {
  return `[${vector.map((value) => Number(value.toFixed(6))).join(",")}]`;
}

export function buildVectorSql(vector: number[]) {
  return sql`${vectorLiteral(vector)}::vector`;
}

export async function isPgvectorAvailable(app: FastifyInstance): Promise<boolean> {
  const cached = pgvectorAvailabilityCache.get(app);
  if (cached) {
    return cached;
  }

  const pending = (async () => {
    try {
      const result = await app.db.execute(sql`
        select exists (
          select 1 from pg_extension where extname = 'vector'
        ) as "ready"
      `);
      const row = Array.isArray(result) ? result[0] : (result as { rows?: Array<Record<string, unknown>> }).rows?.[0];
      return row?.ready === true || row?.ready === "t";
    } catch {
      return false;
    }
  })();

  pgvectorAvailabilityCache.set(app, pending);
  return pending;
}

async function hasKnowledgeChunkEmbeddingColumn(app: FastifyInstance): Promise<boolean> {
  const cached = embeddingColumnAvailabilityCache.get(app);
  if (cached) {
    return cached;
  }

  const pending = (async () => {
    try {
      await app.db.execute(sql`create extension if not exists vector`);
      await app.db.execute(sql`
        alter table knowledge_chunks
          add column if not exists embedding vector(256),
          add column if not exists embedding_v2 vector(384)
      `);
      await app.db.execute(sql`
        create index if not exists knowledge_chunks_embedding_ivfflat_idx
          on knowledge_chunks using ivfflat (embedding vector_cosine_ops)
          with (lists = 100)
      `).catch(() => undefined);
      pgvectorAvailabilityCache.set(app, Promise.resolve(true));
      return true;
    } catch (error) {
      app.log?.warn?.({ error }, "knowledge chunk embedding columns unavailable");
      return false;
    }
  })();

  embeddingColumnAvailabilityCache.set(app, pending);
  return pending;
}

export async function canUseHybridRetrieval(app: FastifyInstance): Promise<boolean> {
  return hasKnowledgeChunkEmbeddingColumn(app);
}

const semanticV2ColumnReady = new WeakMap<FastifyInstance, Promise<boolean>>();
const semanticV2BackfillStarted = new WeakSet<FastifyInstance>();
const SEMANTIC_V2_BACKFILL_BATCH = 16;
const SEMANTIC_V2_BACKFILL_MAX_BATCHES = 12;

/**
 * One-shot background backfill — populates `embedding_v2` for chunks that have
 * a hash embedding but lack a semantic one. Bounded by batch count so it
 * never thrashes the model or DB on a huge corpus. Idempotent: safe to invoke
 * multiple times; subsequent calls see no work to do.
 */
/**
 * Hash embedding sözlüğünü `v1`den `v2`ye taşır (Türkçe kök).
 *
 * Sürüm damgası tek başına yetmez: sorgu tarafı `v2` yazarken indekste `v1`
 * satırlar kaldığı sürece o satırlar bulunamaz hale gelir. Bu yüzden sürüm
 * artışı ile yeniden indeksleme AYNI değişikliğin iki yarısıdır.
 *
 * Partili ve idempotent: her koşu yalnız `v2` olmayan satırlara dokunur,
 * yarıda kesilirse kaldığı yerden devam eder.
 */
export async function backfillHashedEmbeddings(
  app: FastifyInstance,
  options: { maxBatches?: number } = {},
): Promise<{ processed: number; batches: number; stopped: string }> {
  if (!(await hasKnowledgeChunkEmbeddingColumn(app))) {
    return { processed: 0, batches: 0, stopped: "embedding_columns_unavailable" };
  }
  const limit = SEMANTIC_V2_BACKFILL_BATCH;
  const maxBatches = options.maxBatches ?? SEMANTIC_V2_BACKFILL_MAX_BATCHES;
  let processed = 0;
  let batches = 0;
  for (let i = 0; i < maxBatches; i += 1) {
    const rows = await app.db
      .select({ id: knowledgeChunks.id, content: knowledgeChunks.content })
      .from(knowledgeChunks)
      .where(
        and(
          sql`embedding is not null`,
          sql`coalesce(embedding_model, '') <> ${RETRIEVAL_EMBEDDING_MODEL_V2}`,
        ),
      )
      .limit(limit);
    if (rows.length === 0) {
      return { processed, batches, stopped: "complete" };
    }
    for (const row of rows) {
      try {
        // Yeniden indekslemede DAEMON KULLANILMAZ: amaç satırı bilinen bir
        // sözlüğe taşımak. Daemon'ın kendi tokenleştirmesi sürümlenmediği
        // için damga yalan olurdu.
        const vector = buildVectorSql(
          buildHashedKnowledgeEmbedding(row.content, RETRIEVAL_EMBEDDING_MODEL_V2),
        );
        await app.db.execute(sql`
          update knowledge_chunks
          set embedding = ${vector}, embedding_model = ${RETRIEVAL_EMBEDDING_MODEL_V2}
          where id = ${row.id}
        `);
        processed += 1;
      } catch (error) {
        app.log?.warn?.({ error, chunkId: row.id }, "hashed embedding backfill skipped");
      }
    }
    batches += 1;
  }
  return { processed, batches, stopped: "batch_limit" };
}

export async function backfillSemanticV2Embeddings(
  app: FastifyInstance,
  options: { maxBatches?: number } = {},
): Promise<{ processed: number; batches: number; stopped: string }> {
  if (!(await hasKnowledgeChunkEmbeddingColumn(app))) {
    return { processed: 0, batches: 0, stopped: "embedding_columns_unavailable" };
  }
  if (!(await ensureSemanticV2Column(app))) {
    return { processed: 0, batches: 0, stopped: "v2_column_unavailable" };
  }
  const limit = SEMANTIC_V2_BACKFILL_BATCH;
  const maxBatches = options.maxBatches ?? SEMANTIC_V2_BACKFILL_MAX_BATCHES;
  let processed = 0;
  let batches = 0;
  for (let i = 0; i < maxBatches; i += 1) {
    const rows = await app.db
      .select({
        id: knowledgeChunks.id,
        content: knowledgeChunks.content,
      })
      .from(knowledgeChunks)
      .where(
        and(
          // Older indexed chunks may have a vector but no model marker. The
          // vector columns are the durable source of truth; requiring only
          // embedding_model silently made those rows invisible to backfill.
          sql`(embedding is not null or embedding_v2 is not null)`,
          sql`embedding_v2 is null`,
        ),
      )
      .limit(limit);
    if (rows.length === 0) {
      return { processed, batches, stopped: "complete" };
    }
    const vectors = await embedTextsForStorage(
      rows.map((r) => r.content),
      app.log,
    );
    if (!vectors) {
      return { processed, batches, stopped: "model_unavailable" };
    }
    for (let ci = 0; ci < rows.length; ci += 1) {
      try {
        const v2 = buildVectorSql(vectors[ci]!);
        await app.db.execute(sql`
          update knowledge_chunks
          set embedding_v2 = ${v2}
          where id = ${rows[ci]!.id}
        `);
        processed += 1;
      } catch (error) {
        app.log?.warn?.({ error, chunkId: rows[ci]!.id }, "v2 backfill row failed");
      }
    }
    batches += 1;
  }
  return { processed, batches, stopped: "max_batches_reached" };
}

/**
 * Fire-and-forget startup hook — runs the backfill in the background so the
 * server boot isn't blocked while the e5 model warms up. Safe to call from
 * `build-app`: it tracks per-app start so re-registering is a no-op.
 */
export function maybeStartSemanticV2Backfill(app: FastifyInstance): void {
  if (semanticV2BackfillStarted.has(app)) return;
  semanticV2BackfillStarted.add(app);
  // Warm the existing semantic worker in the background even when there are no
  // knowledge chunks to backfill. Otherwise the first real understanding turn
  // pays model cold-start and can time out into the weak hash fallback.
  void (async () => {
    const warmup = await embedTextsForStorage(
      ["Elyan semantic capability routing readiness"],
      app.log,
      "semantic-worker-warmup-v1",
      30_000,
    );
    const result = await backfillSemanticV2Embeddings(app);
    app.log?.info?.(
      { ...result, semanticWorkerWarmed: Boolean(warmup?.[0]) },
      "semantic v2 embedding backfill complete",
    );
  })()
    .catch((error) => app.log?.warn?.({ error }, "semantic v2 backfill failed"));
}

/**
 * Adds the 384-dim `embedding_v2` column the first time it's needed. Idempotent
 * and cached per-app. Returns false if pgvector isn't available so callers can
 * gracefully skip the semantic-v2 path.
 */
async function ensureSemanticV2Column(app: FastifyInstance): Promise<boolean> {
  const cached = semanticV2ColumnReady.get(app);
  if (cached) return cached;
  const pending = (async () => {
    if (!(await isPgvectorAvailable(app))) return false;
    try {
      await app.db.execute(sql`
        alter table knowledge_chunks
          add column if not exists embedding_v2 vector(384)
      `);
      // Birincil semantik filtre embedding_v2 <=> sorgusu; indeks olmadan her
      // arama sequential scan'dı (prod'da HİÇ indeks yoktu). hnsw (pgvector
      // ≥0.5) recall+gecikmede ivfflat'ten iyi; eski sürümde ivfflat'e düş.
      try {
        await app.db.execute(sql`
          create index if not exists knowledge_chunks_embedding_v2_hnsw_idx
            on knowledge_chunks using hnsw (embedding_v2 vector_cosine_ops)
        `);
      } catch (indexError) {
        app.log?.warn?.(
          { error: indexError },
          "hnsw index unavailable; falling back to ivfflat for embedding_v2",
        );
        await app.db.execute(sql`
          create index if not exists knowledge_chunks_embedding_v2_ivfflat_idx
            on knowledge_chunks using ivfflat (embedding_v2 vector_cosine_ops)
            with (lists = 100)
        `).catch(() => undefined);
      }
      return true;
    } catch (error) {
      app.log?.warn?.({ error }, "failed to ensure embedding_v2 column");
      return false;
    }
  })();
  semanticV2ColumnReady.set(app, pending);
  return pending;
}

export async function getRetrievalStatus(app: FastifyInstance, userId: string) {
  const hybridReady = await canUseHybridRetrieval(app);
  try {
    // /readyz uses a synthetic identity to report infrastructure readiness.
    // Applying a user-scoped visibility filter there made a healthy private
    // corpus look empty (and therefore reported lexical_fallback/0), even
    // though the actual user's retrieval path could use its embeddings. The
    // health aggregate contains counts only, never chunk content, so it may
    // inspect all ready documents; normal callers remain user/session scoped.
    const visibility =
      userId === "__health__"
        ? eq(knowledgeDocuments.status, "ready")
        : and(
            eq(knowledgeDocuments.status, "ready"),
            or(eq(knowledgeChunks.scope, "shared"), eq(knowledgeChunks.ownerUserId, userId)),
          );
    const counts = await app.db
      .select({
        totalChunks: sql<number>`count(*)`,
        embeddedChunks: sql<number>`count(*) filter (where embedding is not null or embedding_v2 is not null)`,
        lastIndexedAt: sql<Date | null>`max(${knowledgeChunks.createdAt}) filter (where embedding is not null or embedding_v2 is not null)`,
      })
      .from(knowledgeChunks)
      .innerJoin(knowledgeDocuments, eq(knowledgeDocuments.id, knowledgeChunks.documentId))
      .where(visibility);

    const pendingJobs = await app.db
      .select({
        pending: sql<number>`count(*) filter (where ${trainingJobs.status} in ('queued', 'running'))`,
      })
      .from(trainingJobs)
      .where(eq(trainingJobs.kind, "retrieval_index"));

    const totalChunks = Number(counts[0]?.totalChunks ?? 0);
    const embeddedChunks = Number(counts[0]?.embeddedChunks ?? 0);
    const embeddingCoverage =
      totalChunks <= 0 ? 0 : Number(((embeddedChunks / totalChunks) * 100).toFixed(1));
    const rawLastIndexedAt = counts[0]?.lastIndexedAt;
    let lastIndexedAt: string | null = null;
    if (rawLastIndexedAt) {
      const parsed = rawLastIndexedAt instanceof Date
        ? rawLastIndexedAt
        : new Date(String(rawLastIndexedAt));
      if (!Number.isNaN(parsed.getTime())) {
        lastIndexedAt = parsed.toISOString();
      }
    }

    return {
      mode: hybridReady && embeddedChunks > 0 ? ("hybrid" as const) : ("lexical_fallback" as const),
      hybridReady,
      embeddingCoverage,
      pendingIndexJobs: Number(pendingJobs[0]?.pending ?? 0),
      lastIndexedAt,
    };
  } catch {
    return {
      mode: "lexical_fallback" as const,
      hybridReady: false,
      embeddingCoverage: 0,
      pendingIndexJobs: 0,
      lastIndexedAt: null,
    };
  }
}

function scoreLexicalKnowledgeMatch(
  query: string,
  input: {
    title: string;
    content: string;
    scope: BrainScope;
    ordinal: number;
  },
): number {
  const haystack = `${input.title} ${input.content}`.toLowerCase();
  const queryTokens = contentTerms(query, { limit: 8 });
  const overlap = queryTokens.reduce((count, token) => count + (haystack.includes(token) ? 1 : 0), 0);
  const exactBonus = haystack.includes(query.trim().toLowerCase()) ? 4 : 0;
  const scopeBonus = input.scope === "user" ? 1 : 0;
  return exactBonus + overlap * 2 + scopeBonus - input.ordinal * 0.01;
}

async function searchKnowledgeLexical(
  app: FastifyInstance,
  input: {
    userId: string;
    query: string;
    limit: number;
    scope?: KnowledgeSearchScope;
  },
): Promise<RetrievalSearchResult[]> {
  const normalizedQuery = input.query.trim();
  const queryTokens = contentTerms(normalizedQuery, { limit: 8 });
  const lexicalClauses = [
    ilike(knowledgeChunks.content, `%${normalizedQuery}%`),
    ilike(knowledgeDocuments.title, `%${normalizedQuery}%`),
    ilike(knowledgeDocuments.summary, `%${normalizedQuery}%`),
    ...queryTokens.flatMap((token) => [
      ilike(knowledgeChunks.content, `%${token}%`),
      ilike(knowledgeDocuments.title, `%${token}%`),
      ilike(knowledgeDocuments.summary, `%${token}%`),
    ]),
  ];
  const rows = await app.db
    .select({
      documentId: knowledgeDocuments.id,
      title: knowledgeDocuments.title,
      sourceType: knowledgeDocuments.sourceType,
      sourceUri: knowledgeDocuments.sourceUri,
      summary: knowledgeDocuments.summary,
      scope: knowledgeChunks.scope,
      chunkId: knowledgeChunks.id,
      ordinal: knowledgeChunks.ordinal,
      content: knowledgeChunks.content,
      tokenEstimate: knowledgeChunks.tokenEstimate,
      metadata: knowledgeChunks.metadata,
      updatedAt: knowledgeDocuments.updatedAt,
    })
    .from(knowledgeChunks)
    .innerJoin(knowledgeDocuments, eq(knowledgeDocuments.id, knowledgeChunks.documentId))
    .where(
      and(
        eq(knowledgeDocuments.status, "ready"),
        knowledgeVisibility(input.userId, input.scope),
        or(...lexicalClauses),
      ),
    )
    .orderBy(desc(knowledgeDocuments.updatedAt))
    .limit(Math.max(input.limit * 5, 20));

  return rows
    .map((row) => ({
      ...row,
      score: scoreLexicalKnowledgeMatch(input.query, {
        title: row.title,
        content: row.content,
        scope: row.scope,
        ordinal: row.ordinal,
      }),
    }))
    .sort((left, right) => right.score - left.score)
    .slice(0, input.limit);
}

async function searchKnowledgeHybrid(
  app: FastifyInstance,
  input: {
    userId: string;
    query: string;
    limit: number;
    scope?: KnowledgeSearchScope;
    queryVector?: number[] | null;
  },
): Promise<RetrievalSearchResult[]> {
  // Storage embedding strategy:
  //   • Primary: 384-dim real semantic (embedding_v2, e5-small) when the model
  //     loaded AND we can compute a query vector with matching dims.
  //   • Fallback: 256-dim hash embedding (always available, fast).
  // Chunks that don't yet have a v2 vector are matched via the hash fallback,
  // so the upgrade is incremental and zero-downtime.
  const v2ColumnReady = await ensureSemanticV2Column(app);
  const semanticQueryVector = v2ColumnReady
    ? input.queryVector === undefined
      ? await embedQueryForStorage(input.query, app.log, `user:${input.userId}`).catch(() => null)
      : input.queryVector
    : null;
  const hashVector = buildVectorSql(await buildEmbedding(input.query));
  const candidateLimit = Math.max(input.limit * 6, 24);
  const visibilitySql =
    input.scope === "system_corpus"
      ? sql`kc.scope = 'shared' and kd.metadata->>'elyanCorpusPurpose' = 'knowledge'`
      : sql`(kc.scope = 'shared' or kc.owner_user_id = ${input.userId})`;

  let rows: unknown;
  if (semanticQueryVector) {
    const v2QueryVector = buildVectorSql(semanticQueryVector);
    rows = await app.db.execute(sql`
      select
        kd.id as "documentId",
        kd.title as "title",
        kd.source_type as "sourceType",
        kd.source_uri as "sourceUri",
        kd.summary as "summary",
        kc.scope as "scope",
        kc.id as "chunkId",
        kc.ordinal as "ordinal",
        kc.content as "content",
        kc.token_estimate as "tokenEstimate",
        kc.metadata as "metadata",
        kd.updated_at as "updatedAt",
        case
          when kc.embedding_v2 is not null then 1 - (kc.embedding_v2 <=> ${v2QueryVector})
          else 1 - (kc.embedding <=> ${hashVector})
        end as "semanticScore"
      from knowledge_chunks kc
      inner join knowledge_documents kd on kd.id = kc.document_id
      where kd.status = 'ready'
        and (${visibilitySql})
        and (kc.embedding is not null or kc.embedding_v2 is not null)
      order by
        case
          when kc.embedding_v2 is not null then kc.embedding_v2 <=> ${v2QueryVector}
          else kc.embedding <=> ${hashVector}
        end
      limit ${candidateLimit}
    `);
  } else {
    rows = await app.db.execute(sql`
      select
        kd.id as "documentId",
        kd.title as "title",
        kd.source_type as "sourceType",
        kd.source_uri as "sourceUri",
        kd.summary as "summary",
        kc.scope as "scope",
        kc.id as "chunkId",
        kc.ordinal as "ordinal",
        kc.content as "content",
        kc.token_estimate as "tokenEstimate",
        kc.metadata as "metadata",
        kd.updated_at as "updatedAt",
        1 - (kc.embedding <=> ${hashVector}) as "semanticScore"
      from knowledge_chunks kc
      inner join knowledge_documents kd on kd.id = kc.document_id
      where kd.status = 'ready'
        and (${visibilitySql})
        and (kc.embedding is not null or kc.embedding_v2 is not null)
      order by kc.embedding <=> ${hashVector}
      limit ${candidateLimit}
    `);
  }

  const rawRows = Array.isArray(rows) ? rows : (rows as { rows?: Array<Record<string, unknown>> }).rows ?? [];
  return rawRows
    .map((row) => {
      const scope = String(row.scope ?? "user") as BrainScope;
      const lexicalScore = scoreLexicalKnowledgeMatch(input.query, {
        title: String(row.title ?? ""),
        content: String(row.content ?? ""),
        scope,
        ordinal: Number(row.ordinal ?? 0),
      });
      const semanticScore = Number(row.semanticScore ?? 0);
      return {
        documentId: String(row.documentId),
        chunkId: String(row.chunkId),
        title: String(row.title ?? ""),
        scope,
        sourceType: String(row.sourceType ?? "note"),
        sourceUri: row.sourceUri == null ? null : String(row.sourceUri),
        summary: row.summary == null ? null : String(row.summary),
        content: String(row.content ?? ""),
        tokenEstimate: Number(row.tokenEstimate ?? 0),
        ordinal: Number(row.ordinal ?? 0),
        metadata: row.metadata ?? {},
        updatedAt: row.updatedAt instanceof Date ? row.updatedAt : new Date(String(row.updatedAt ?? Date.now())),
        score: Number((semanticScore * 0.65 + Math.min(lexicalScore / 10, 1) * 0.35).toFixed(4)),
      } satisfies RetrievalSearchResult;
    })
    .sort((left, right) => right.score - left.score)
    .slice(0, input.limit);
}

export function fuseRetrievalCandidates(
  lists: RetrievalSearchResult[][],
): RetrievalSearchResult[] {
  const fused = new Map<
    string,
    { item: RetrievalSearchResult; score: number }
  >();
  for (const results of lists) {
    results.forEach((item, rank) => {
      const contribution = 1 / (60 + rank + 1);
      const existing = fused.get(item.chunkId);
      if (existing) {
        existing.score += contribution;
      } else {
        fused.set(item.chunkId, { item, score: contribution });
      }
    });
  }
  return [...fused.values()]
    .sort((left, right) => right.score - left.score)
    .map(({ item, score }) => ({
      ...item,
      score: Number(score.toFixed(6)),
    }));
}

export async function searchKnowledge(
  app: FastifyInstance,
  input: {
    userId: string;
    query: string;
    limit: number;
    semanticRerankReady?: boolean;
    scope?: KnowledgeSearchScope;
    queryVector?: number[] | null;
  },
) {
  const hybridReady = await canUseHybridRetrieval(app);
  const [hybridResults, lexicalResults] = hybridReady
    ? await Promise.all([
        searchKnowledgeHybrid(app, input),
        searchKnowledgeLexical(app, input),
      ])
    : [[], await searchKnowledgeLexical(app, input)];
  const mergedResults = hybridReady
    ? fuseRetrievalCandidates([hybridResults, lexicalResults])
    : lexicalResults;
  const reranked = await rerankSemanticCandidates({
    query: input.query,
    candidates: mergedResults,
    enabled:
      app.config.ELYAN_RAG_SEMANTIC_RERANK_ENABLED &&
      input.semanticRerankReady !== false,
    modelName: app.config.ELYAN_RAG_SEMANTIC_RERANK_MODEL,
    windowSize: app.config.ELYAN_RAG_SEMANTIC_RERANK_WINDOW,
    cacheScope: `user:${input.userId}`,
    logger: app.log,
  });

  return {
    retrievalMode: hybridReady ? ("hybrid" as const) : ("lexical_fallback" as const),
    results: reranked.results.slice(0, input.limit),
    retrievalResultCount: reranked.results.slice(0, input.limit).length,
    lexicalCandidateCount: lexicalResults.length,
    semanticCandidateCount: hybridResults.length,
    candidateCount: mergedResults.length,
    rerankUsed: reranked.used,
    rerankDegradedReason: reranked.degradedReason,
    degradedReason:
      hybridReady && hybridResults.length === 0 && lexicalResults.length > 0
        ? "hybrid_results_cold_lexical_used"
        : hybridReady
          ? null
          : "hybrid_retrieval_unavailable",
  };
}

export async function indexKnowledgeChunksForDocument(
  app: FastifyInstance,
  input: {
    documentId: string;
  },
) {
  if (!(await canUseHybridRetrieval(app))) {
    return {
      indexedChunkCount: 0,
      mode: "lexical_fallback" as const,
      skippedReason: "hybrid_retrieval_unavailable",
    };
  }

  const chunks = await app.db
    .select({
      id: knowledgeChunks.id,
      content: knowledgeChunks.content,
    })
    .from(knowledgeChunks)
    .where(eq(knowledgeChunks.documentId, input.documentId))
    .orderBy(knowledgeChunks.ordinal);

  const indexedAt = new Date().toISOString();
  /* Build all embeddings concurrently (C daemon queues IPC internally) */
  const vectors = await Promise.all(chunks.map((chunk) => buildEmbedding(chunk.content)));

  // Real semantic embeddings (e5-small, 384-dim) populated alongside the hash
  // vectors. The hash stays as the always-available fallback; v2 becomes the
  // primary similarity signal when present. Best-effort: a model load failure
  // never blocks the legacy hash path.
  const v2Ready = await ensureSemanticV2Column(app);
  const v2Vectors = v2Ready
    ? await embedTextsForStorage(
        chunks.map((c) => c.content),
        app.log,
      )
    : null;

  for (let ci = 0; ci < chunks.length; ci++) {
    const embedding = buildVectorSql(vectors[ci]!);
    await app.db.execute(sql`
      update knowledge_chunks
      set
        embedding = ${embedding},
        embedding_model = ${RETRIEVAL_EMBEDDING_MODEL},
        metadata = jsonb_set(
          coalesce(metadata, '{}'::jsonb),
          '{indexedAt}',
          to_jsonb(${indexedAt}::text),
          true
        )
      where id = ${chunks[ci]!.id}
    `);
    if (v2Vectors && v2Vectors[ci]) {
      try {
        const v2 = buildVectorSql(v2Vectors[ci]!);
        await app.db.execute(sql`
          update knowledge_chunks
          set
            embedding_v2 = ${v2},
            metadata = jsonb_set(
              coalesce(metadata, '{}'::jsonb),
              '{semanticModel}',
              to_jsonb(${STORAGE_SEMANTIC_MODEL_TAG}::text),
              true
            )
          where id = ${chunks[ci]!.id}
        `);
      } catch (error) {
        app.log?.warn?.(
          { error, chunkId: chunks[ci]!.id },
          "embedding_v2 write skipped",
        );
      }
    }
  }

  return {
    indexedChunkCount: chunks.length,
    mode: "hybrid" as const,
    skippedReason: null,
  };
}
