import { createHash, randomUUID } from 'crypto';
import { readFile } from 'fs/promises';
import { getControlPlanePool } from '@/core/control-plane/database';
import { env } from '@/lib/env';
import {
  buildTextEmbedding,
  normalizeRetrievalText,
  toPgVectorLiteral,
  truncateRetrievalText,
} from './embeddings';

export type RetrievalDocumentSourceKind = 'web' | 'bootstrap' | 'interaction' | 'learning';

export type RetrievalDocumentInput = {
  accountId?: string | null;
  sourceKind: RetrievalDocumentSourceKind;
  sourceName: string;
  sourceUrl?: string | null;
  title?: string | null;
  content: string;
  metadata?: Record<string, unknown>;
  createdAt?: string;
  updatedAt?: string;
};

export type RetrievalDocumentRecord = {
  documentId: string;
  accountId?: string | null;
  sourceKind: RetrievalDocumentSourceKind;
  sourceName: string;
  sourceUrl?: string | null;
  title?: string | null;
  content: string;
  contentHash: string;
  metadata: Record<string, unknown>;
  createdAt: string;
  updatedAt: string;
  similarity?: number;
  keywordScore?: number;
  combinedScore?: number;
};

const RETRIEVAL_DOCUMENTS_TABLE = 'retrieval_documents';
let retrievalDocumentIdColumnPromise: Promise<string> | null = null;

function getDatabaseUrl() {
  return env.DATABASE_URL?.trim() || process.env.DATABASE_URL?.trim() || '';
}

function createContentHash(input: Pick<RetrievalDocumentInput, 'sourceKind' | 'sourceName' | 'sourceUrl' | 'content'>) {
  return createHash('sha256')
    .update(JSON.stringify({
      sourceKind: input.sourceKind,
      sourceName: input.sourceName,
      sourceUrl: input.sourceUrl ?? null,
      content: normalizeRetrievalText(input.content),
    }))
    .digest('hex');
}

async function readBootstrapText(pathname: string) {
  const text = await readFile(pathname, 'utf8');
  return text;
}

function normalizeSearchQuery(query: string) {
  return normalizeRetrievalText(query).trim();
}

async function resolveRetrievalDocumentIdColumn() {
  if (!retrievalDocumentIdColumnPromise) {
    retrievalDocumentIdColumnPromise = (async () => {
      const databaseUrl = getDatabaseUrl();
      if (!databaseUrl) {
        return 'document_id';
      }

      const pool = getControlPlanePool(databaseUrl);
      const result = await pool.query<{ column_name: string }>(
        `
          SELECT column_name
          FROM information_schema.columns
          WHERE table_schema = 'public'
            AND table_name = $1
            AND column_name IN ('document_id', 'id')
          ORDER BY CASE column_name WHEN 'document_id' THEN 0 ELSE 1 END
          LIMIT 1
        `,
        [RETRIEVAL_DOCUMENTS_TABLE]
      );

      return result.rows[0]?.column_name ?? 'document_id';
    })();
  }

  return retrievalDocumentIdColumnPromise;
}

function mergeSearchScores(vectorScore?: number, keywordScore?: number) {
  const normalizedVector = typeof vectorScore === 'number' && Number.isFinite(vectorScore) ? Math.max(0, Math.min(1, vectorScore)) : 0;
  const normalizedKeyword = typeof keywordScore === 'number' && Number.isFinite(keywordScore) ? Math.max(0, Math.min(1, keywordScore)) : 0;

  if (normalizedVector === 0 && normalizedKeyword === 0) {
    return 0;
  }

  return Number((normalizedVector * 0.6 + normalizedKeyword * 0.4).toFixed(6));
}

export async function loadTextFromSource(input: { url?: string; path?: string }) {
  if (input.path) {
    return readBootstrapText(input.path);
  }

  if (!input.url) {
    return '';
  }

  const response = await fetch(input.url, {
    headers: {
      'User-Agent': 'Elyan-Selective-Ingestion/1.0',
    },
    signal: AbortSignal.timeout(15_000),
  });

  if (!response.ok) {
    throw new Error(`Unable to download bootstrap source: HTTP ${response.status}`);
  }

  return response.text();
}

export async function upsertRetrievalDocument(input: RetrievalDocumentInput) {
  const databaseUrl = getDatabaseUrl();
  if (!databaseUrl) {
    return null;
  }

  const pool = getControlPlanePool(databaseUrl);
  const content = truncateRetrievalText(normalizeRetrievalText(input.content));
  if (content.length === 0) {
    return null;
  }

  const embedding = buildTextEmbedding([
    input.sourceKind,
    input.sourceName,
    input.title ?? '',
    input.sourceUrl ?? '',
    content,
  ].join('\n'));
  const contentHash = createContentHash({ ...input, content });
  const documentId = randomUUID();
  const documentIdColumn = await resolveRetrievalDocumentIdColumn();
  const timestamp = input.createdAt ?? new Date().toISOString();
  const metadata = {
    ...(input.metadata ?? {}),
    source_kind: input.sourceKind,
    source_name: input.sourceName,
    source_url: input.sourceUrl ?? null,
  };

  await pool.query(
    `
      INSERT INTO ${RETRIEVAL_DOCUMENTS_TABLE} (
        ${documentIdColumn},
        account_id,
        source_kind,
        source_name,
        source_url,
        title,
        content,
        content_hash,
        embedding,
        metadata,
        created_at,
        updated_at
      )
      VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9::vector, $10::jsonb, $11::timestamptz, $12::timestamptz)
      ON CONFLICT (content_hash) DO UPDATE SET
        account_id = EXCLUDED.account_id,
        source_kind = EXCLUDED.source_kind,
        source_name = EXCLUDED.source_name,
        source_url = EXCLUDED.source_url,
        title = EXCLUDED.title,
        content = EXCLUDED.content,
        embedding = EXCLUDED.embedding,
        metadata = EXCLUDED.metadata,
        updated_at = EXCLUDED.updated_at
    `,
    [
      documentId,
      input.accountId ?? null,
      input.sourceKind,
      input.sourceName,
      input.sourceUrl ?? null,
      input.title ?? null,
      content,
      contentHash,
      toPgVectorLiteral(embedding),
      JSON.stringify(metadata),
      timestamp,
      input.updatedAt ?? timestamp,
    ]
  );

  return {
    documentId,
    contentHash,
    embedding,
    content,
  };
}

export async function searchRetrievalDocuments(
  query: string,
  options?: {
    accountId?: string | null;
    sourceKinds?: RetrievalDocumentSourceKind[];
    limit?: number;
  }
) {
  const databaseUrl = getDatabaseUrl();
  if (!databaseUrl) {
    return [];
  }

  const pool = getControlPlanePool(databaseUrl);
  const documentIdColumn = await resolveRetrievalDocumentIdColumn();
  const vector = toPgVectorLiteral(buildTextEmbedding(query));
  const limit = Math.max(1, options?.limit ?? 5);
  const sourceKinds = options?.sourceKinds ?? ['web', 'bootstrap', 'learning'];
  const accountId = options?.accountId ?? null;

  const result = await pool.query<{
    document_id: string;
    account_id: string | null;
    source_kind: RetrievalDocumentSourceKind;
    source_name: string;
    source_url: string | null;
    title: string | null;
    content: string;
    metadata: Record<string, unknown> | null;
    created_at: string;
    similarity: number;
  }>(
    `
      SELECT
        ${documentIdColumn} AS document_id,
        account_id,
        source_kind,
        source_name,
        source_url,
        title,
        content,
        metadata,
        created_at,
        1 - (embedding <=> $1::vector) AS similarity
      FROM ${RETRIEVAL_DOCUMENTS_TABLE}
      WHERE ($2::text[] IS NULL OR source_kind = ANY($2::text[]))
        AND ($3::text IS NULL OR account_id = $3::text OR account_id IS NULL)
      ORDER BY embedding <=> $1::vector, created_at DESC
      LIMIT $4
    `,
    [vector, sourceKinds.length > 0 ? sourceKinds : null, accountId, limit]
  );

  return result.rows.map((row): RetrievalDocumentRecord => ({
    documentId: row.document_id,
    accountId: row.account_id,
    sourceKind: row.source_kind,
    sourceName: row.source_name,
    sourceUrl: row.source_url,
    title: row.title,
    content: row.content,
    contentHash: createHash('sha256').update(row.content).digest('hex'),
    metadata: row.metadata ?? {},
    createdAt: row.created_at,
    updatedAt: row.created_at,
    similarity: Number(Number(row.similarity).toFixed(6)),
  }));
}

export async function searchRetrievalDocumentsByKeyword(
  query: string,
  options?: {
    accountId?: string | null;
    sourceKinds?: RetrievalDocumentSourceKind[];
    limit?: number;
  }
) {
  const databaseUrl = getDatabaseUrl();
  if (!databaseUrl) {
    return [];
  }

  const normalizedQuery = normalizeSearchQuery(query);
  if (!normalizedQuery) {
    return [];
  }

  const pool = getControlPlanePool(databaseUrl);
  const documentIdColumn = await resolveRetrievalDocumentIdColumn();
  const limit = Math.max(1, options?.limit ?? 5);
  const sourceKinds = options?.sourceKinds ?? ['web', 'bootstrap', 'learning'];
  const accountId = options?.accountId ?? null;

  const result = await pool.query<{
    document_id: string;
    account_id: string | null;
    source_kind: RetrievalDocumentSourceKind;
    source_name: string;
    source_url: string | null;
    title: string | null;
    content: string;
    metadata: Record<string, unknown> | null;
    created_at: string;
    keyword_score: number;
  }>(
    `
      WITH query AS (
        SELECT websearch_to_tsquery('english', $1) AS tsq
      )
      SELECT
        ${documentIdColumn} AS document_id,
        account_id,
        source_kind,
        source_name,
        source_url,
        title,
        content,
        metadata,
        created_at,
        ts_rank_cd(
          to_tsvector('english', coalesce(title, '') || ' ' || coalesce(source_name, '') || ' ' || content),
          query.tsq
        ) AS keyword_score
      FROM ${RETRIEVAL_DOCUMENTS_TABLE}
      CROSS JOIN query
      WHERE ($2::text[] IS NULL OR source_kind = ANY($2::text[]))
        AND ($3::text IS NULL OR account_id = $3::text OR account_id IS NULL)
        AND query.tsq @@ to_tsvector('english', coalesce(title, '') || ' ' || coalesce(source_name, '') || ' ' || content)
      ORDER BY keyword_score DESC, created_at DESC
      LIMIT $4
    `,
    [normalizedQuery, sourceKinds.length > 0 ? sourceKinds : null, accountId, limit]
  );

  return result.rows.map((row): RetrievalDocumentRecord => ({
    documentId: row.document_id,
    accountId: row.account_id,
    sourceKind: row.source_kind,
    sourceName: row.source_name,
    sourceUrl: row.source_url,
    title: row.title,
    content: row.content,
    contentHash: createHash('sha256').update(row.content).digest('hex'),
    metadata: row.metadata ?? {},
    createdAt: row.created_at,
    updatedAt: row.created_at,
    keywordScore: Number(Number(row.keyword_score).toFixed(6)),
  }));
}

export async function searchRetrievalDocumentsHybrid(
  query: string,
  options?: {
    accountId?: string | null;
    sourceKinds?: RetrievalDocumentSourceKind[];
    limit?: number;
  }
) {
  const limit = Math.max(1, options?.limit ?? 5);
  const [vectorResults, keywordResults] = await Promise.all([
    searchRetrievalDocuments(query, { ...options, limit: Math.max(limit * 2, limit) }),
    searchRetrievalDocumentsByKeyword(query, { ...options, limit: Math.max(limit * 2, limit) }),
  ]);

  const merged = new Map<string, RetrievalDocumentRecord>();

  for (const record of vectorResults) {
    merged.set(record.documentId, {
      ...record,
      combinedScore: mergeSearchScores(record.similarity, record.keywordScore),
    });
  }

  for (const record of keywordResults) {
    const existing = merged.get(record.documentId);
    merged.set(record.documentId, {
      ...(existing ?? record),
      ...record,
      similarity: existing?.similarity ?? record.similarity,
      keywordScore: record.keywordScore ?? existing?.keywordScore,
      combinedScore: mergeSearchScores(existing?.similarity ?? record.similarity, record.keywordScore),
    });
  }

  return [...merged.values()]
    .sort((left, right) => {
      const leftScore = left.combinedScore ?? left.similarity ?? left.keywordScore ?? 0;
      const rightScore = right.combinedScore ?? right.similarity ?? right.keywordScore ?? 0;

      return rightScore - leftScore || Date.parse(right.createdAt) - Date.parse(left.createdAt);
    })
    .slice(0, limit);
}

export async function ingestRetrievalText(input: RetrievalDocumentInput) {
  const stored = await upsertRetrievalDocument(input);
  return stored;
}
