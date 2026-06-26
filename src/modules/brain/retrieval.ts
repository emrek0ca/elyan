import { createHash } from "node:crypto";
import { and, desc, eq, ilike, or, sql } from "drizzle-orm";
import type { FastifyInstance } from "fastify";
import { knowledgeChunks, knowledgeDocuments, trainingJobs } from "../../db/schema.js";
import type { BrainScope } from "../../contracts/domain.js";
import { rerankSemanticCandidates } from "./semantic-rerank.js";
import { nlpDaemon } from "../../lib/nlp-daemon.js";

const RETRIEVAL_VECTOR_DIMENSIONS = 256;
export const RETRIEVAL_EMBEDDING_MODEL = "elyan_hash_v1";

const pgvectorAvailabilityCache = new WeakMap<FastifyInstance, Promise<boolean>>();
const embeddingColumnAvailabilityCache = new WeakMap<FastifyInstance, Promise<boolean>>();

type RetrievalSearchResult = {
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

function compactText(value: string): string {
  return value.replace(/\s+/g, " ").trim();
}

function tokenize(text: string): string[] {
  return compactText(text)
    .toLowerCase()
    .replace(/[^a-z0-9çğıöşü_\s.-]/gi, " ")
    .split(/\s+/)
    .filter((token) => token.length >= 2)
    .slice(0, 120);
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

export function buildHashedKnowledgeEmbedding(text: string): number[] {
  const vector = new Array<number>(RETRIEVAL_VECTOR_DIMENSIONS).fill(0);
  const tokens = tokenize(text);
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
  return buildHashedKnowledgeEmbedding(text);
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
      const result = await app.db.execute(sql`
        select exists (
          select 1
          from information_schema.columns
          where table_schema = 'public'
            and table_name = 'knowledge_chunks'
            and column_name = 'embedding'
        ) as "ready"
      `);
      const row = Array.isArray(result) ? result[0] : (result as { rows?: Array<Record<string, unknown>> }).rows?.[0];
      return row?.ready === true || row?.ready === "t";
    } catch {
      return false;
    }
  })();

  embeddingColumnAvailabilityCache.set(app, pending);
  return pending;
}

export async function canUseHybridRetrieval(app: FastifyInstance): Promise<boolean> {
  const [extensionReady, columnReady] = await Promise.all([
    isPgvectorAvailable(app),
    hasKnowledgeChunkEmbeddingColumn(app),
  ]);
  return extensionReady && columnReady;
}

export async function getRetrievalStatus(app: FastifyInstance, userId: string) {
  const hybridReady = await canUseHybridRetrieval(app);
  try {
    const counts = await app.db
      .select({
        totalChunks: sql<number>`count(*)`,
        embeddedChunks: sql<number>`count(*) filter (where ${knowledgeChunks.embeddingModel} is not null)`,
        lastIndexedAt: sql<Date | null>`max(${knowledgeChunks.createdAt}) filter (where ${knowledgeChunks.embeddingModel} is not null)`,
      })
      .from(knowledgeChunks)
      .leftJoin(knowledgeDocuments, eq(knowledgeDocuments.id, knowledgeChunks.documentId))
      .where(
        and(
          eq(knowledgeDocuments.status, "ready"),
          or(eq(knowledgeChunks.scope, "shared"), eq(knowledgeChunks.ownerUserId, userId)),
        ),
      );

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

    return {
      mode: hybridReady && embeddedChunks > 0 ? ("hybrid" as const) : ("lexical_fallback" as const),
      hybridReady,
      embeddingCoverage,
      pendingIndexJobs: Number(pendingJobs[0]?.pending ?? 0),
      lastIndexedAt: counts[0]?.lastIndexedAt?.toISOString() ?? null,
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
  const queryTokens = tokenize(query);
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
  },
): Promise<RetrievalSearchResult[]> {
  const normalizedQuery = input.query.trim();
  const queryTokens = [...new Set(tokenize(normalizedQuery).slice(0, 8))];
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
        or(eq(knowledgeChunks.scope, "shared"), eq(knowledgeChunks.ownerUserId, input.userId)),
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
  },
): Promise<RetrievalSearchResult[]> {
  const queryVector = buildVectorSql(await buildEmbedding(input.query));
  const rows = await app.db.execute(sql`
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
      1 - (kc.embedding <=> ${queryVector}) as "semanticScore"
    from knowledge_chunks kc
    inner join knowledge_documents kd on kd.id = kc.document_id
    where kd.status = 'ready'
      and (kc.scope = 'shared' or kc.owner_user_id = ${input.userId})
      and kc.embedding_model is not null
    order by kc.embedding <=> ${queryVector}
    limit ${Math.max(input.limit * 6, 24)}
  `);

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

export async function searchKnowledge(
  app: FastifyInstance,
  input: {
    userId: string;
    query: string;
    limit: number;
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
    ? [...hybridResults, ...lexicalResults]
        .reduce<RetrievalSearchResult[]>((acc, item) => {
          if (acc.some((existing) => existing.chunkId === item.chunkId)) {
            return acc;
          }
          acc.push(item);
          return acc;
        }, [])
        .sort((left, right) => right.score - left.score)
    : lexicalResults;
  const reranked = await rerankSemanticCandidates({
    query: input.query,
    candidates: mergedResults,
    enabled: app.config.ELYAN_RAG_SEMANTIC_RERANK_ENABLED,
    modelName: app.config.ELYAN_RAG_SEMANTIC_RERANK_MODEL,
    windowSize: app.config.ELYAN_RAG_SEMANTIC_RERANK_WINDOW,
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
  }

  return {
    indexedChunkCount: chunks.length,
    mode: "hybrid" as const,
    skippedReason: null,
  };
}
