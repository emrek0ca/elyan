import { createHash } from "node:crypto";
import { readFile } from "node:fs/promises";
import { join } from "node:path";
import { and, eq, sql } from "drizzle-orm";
import type { FastifyInstance } from "fastify";
import { knowledgeChunks, knowledgeDocuments } from "../../db/schema.js";
import { indexKnowledgeChunksForDocument } from "./retrieval.js";
import { nlpDaemon } from "../../lib/nlp-daemon.js";
import { collapseWhitespace as compactText } from "../../lib/text.js";

export const ELYAN_BRAIN_CORPUS_VERSION = "2026-06-v1";

export type BrainCorpusDomain =
  | "memory"
  | "skills"
  | "design"
  | "code"
  | "language"
  | "data"
  | "reasoning"
  | "safety";

type BrainCorpusSource = {
  id: string;
  domain: BrainCorpusDomain;
  title: string;
  fileName: string;
  tags: string[];
  priority: number;
};

export type BrainCorpusDocumentManifest = BrainCorpusSource & {
  version: string;
  sourceUri: string;
  contentHash: string;
  characterCount: number;
};

const CORPUS_SOURCES: BrainCorpusSource[] = [
  {
    id: "elyan.brain.memory",
    domain: "memory",
    title: "Elyan Memory Protocol",
    fileName: "memory.md",
    tags: ["memory", "episodic", "facts", "profile", "retention"],
    priority: 90,
  },
  {
    id: "elyan.brain.skills",
    domain: "skills",
    title: "Elyan Skill and Capability Protocol",
    fileName: "skills.md",
    tags: ["skills", "routing", "tools", "attachments", "desktop-runtime"],
    priority: 88,
  },
  {
    id: "elyan.brain.design",
    domain: "design",
    title: "Elyan Design Language",
    fileName: "design.md",
    tags: ["design", "website", "pdf", "presentation", "visual-output"],
    priority: 86,
  },
  {
    id: "elyan.brain.code",
    domain: "code",
    title: "Elyan Code Engineering Protocol",
    fileName: "code.md",
    tags: ["code", "debug", "tests", "architecture", "refactor"],
    priority: 86,
  },
  {
    id: "elyan.brain.language",
    domain: "language",
    title: "Elyan Language Protocol",
    fileName: "language.md",
    tags: ["language", "turkish", "english", "translation", "writing"],
    priority: 82,
  },
  {
    id: "elyan.brain.data",
    domain: "data",
    title: "Elyan Data and Document Protocol",
    fileName: "data.md",
    tags: ["data", "documents", "tables", "charts", "citations"],
    priority: 84,
  },
  {
    id: "elyan.brain.reasoning",
    domain: "reasoning",
    title: "Elyan Reasoning Protocol",
    fileName: "reasoning.md",
    tags: ["reasoning", "planning", "verification", "uncertainty"],
    priority: 84,
  },
  {
    id: "elyan.brain.safety",
    domain: "safety",
    title: "Elyan Safety Protocol",
    fileName: "safety.md",
    tags: ["safety", "privacy", "permissions", "boundary", "disclosure"],
    priority: 92,
  },
];

function hashText(value: string): string {
  return createHash("sha256").update(value).digest("hex");
}

function corpusDir(): string {
  return join(process.cwd(), "src", "modules", "brain", "corpus");
}

async function readCorpusFile(fileName: string): Promise<string> {
  return readFile(join(corpusDir(), fileName), "utf8");
}

function chunkMarkdown(content: string): Array<{ content: string; tokenEstimate: number; metadata: Record<string, unknown> }> {
  const sections = content
    .split(/\n(?=##\s+)/g)
    .map((section) => section.trim())
    .filter(Boolean);
  const chunks = sections.length ? sections : [content.trim()].filter(Boolean);
  return chunks.map((chunk, index) => ({
    content: chunk,
    tokenEstimate: Math.max(1, Math.ceil(compactText(chunk).length / 4)),
    metadata: {
      chunkSource: "system_corpus_markdown",
      chunkIndex: index,
    },
  }));
}

export function detectBrainCorpusDomains(prompt: string): BrainCorpusDomain[] {
  const normalized = prompt.toLowerCase();
  const domains: BrainCorpusDomain[] = [];
  const add = (domain: BrainCorpusDomain) => {
    if (!domains.includes(domain)) {
      domains.push(domain);
    }
  };

  if (/\b(design|website|web site|landing|ui|ux|pdf|presentation|sunum|tasar|gorsel|visual|layout|typography)\b/u.test(normalized)) {
    add("design");
  }
  if (/\b(code|kod|debug|bug|test|refactor|api|typescript|python|flutter|electron|sql|migrate|deploy)\b/u.test(normalized)) {
    add("code");
  }
  if (/\b(cevir|translate|dil|language|rewrite|writing|metin|yazi|ozet|summary|tone|uslup|turkce|english)\b/u.test(normalized)) {
    add("language");
  }
  if (/\b(data|veri|tablo|csv|excel|spreadsheet|chart|grafik|document|belge|pdf|ocr|rapor|analyze|analiz)\b/u.test(normalized)) {
    add("data");
  }
  if (/\b(skill|beceri|tool|arac|mcp|runtime|desktop|operator|attachment|ek|dosya)\b/u.test(normalized)) {
    add("skills");
  }
  if (/\b(memory|hafiza|hatirla|remember|profil|preference|tercih|gecmis)\b/u.test(normalized)) {
    add("memory");
  }
  if (/\b(plan|reason|dusun|karar|verify|dogrula|belirsiz|uncertain|risk)\b/u.test(normalized)) {
    add("reasoning");
  }
  if (/\b(safety|guvenlik|gizli|private|permission|izin|provider|model|prompt|credential|token)\b/u.test(normalized)) {
    add("safety");
  }

  return domains;
}

// ── Deterministic corpus guidance injection (RAM-cached, C-BM25 ranked) ──────
//
// The corpus is also seeded into the knowledge DB for RAG, but prod retrieval is
// lexical-fallback (no embeddings), so design/skill guidance was not reliably
// surfacing for "rapor/tablo/pdf yap" prompts. Here we inject it deterministically:
//   * corpus markdown is read from disk ONCE and cached in-process (a few KB total,
//     no per-request I/O, no DB query — saves server storage + RAM churn),
//   * for the detected domain we pick the single most relevant `##` section using
//     the C NLP daemon's BM25 (fast, native), falling back to a tiny lexical scorer,
//   * only that capped section is injected, keeping the prompt token-cheap.

const corpusSectionCache = new Map<BrainCorpusDomain, string[]>();
const GUIDANCE_DOMAIN_LIMIT = 2;
const GUIDANCE_SECTION_CHARS = 620;

async function loadCorpusSectionsCached(
  domain: BrainCorpusDomain,
): Promise<string[]> {
  const cached = corpusSectionCache.get(domain);
  if (cached) {
    return cached;
  }
  const source = CORPUS_SOURCES.find((entry) => entry.domain === domain);
  if (!source) {
    corpusSectionCache.set(domain, []);
    return [];
  }
  try {
    const content = await readCorpusFile(source.fileName);
    const sections = content
      .split(/\n(?=##\s+)/g)
      .map((section) => section.trim())
      .filter(Boolean);
    corpusSectionCache.set(domain, sections);
    return sections;
  } catch {
    corpusSectionCache.set(domain, []);
    return [];
  }
}

function lexicalBestSectionIndex(prompt: string, sections: string[]): number {
  const terms = new Set(
    compactText(prompt)
      .toLowerCase()
      .split(" ")
      .filter((term) => term.length > 2),
  );
  let bestIndex = 0;
  let bestScore = -1;
  sections.forEach((section, index) => {
    const text = section.toLowerCase();
    let score = 0;
    for (const term of terms) {
      if (text.includes(term)) {
        score += 1;
      }
    }
    if (score > bestScore) {
      bestScore = score;
      bestIndex = index;
    }
  });
  return bestIndex;
}

async function pickBestCorpusSection(
  prompt: string,
  sections: string[],
): Promise<string | null> {
  if (sections.length === 0) {
    return null;
  }
  if (sections.length === 1) {
    return sections[0];
  }
  try {
    const scores = await nlpDaemon.bm25Batch(
      prompt,
      sections.map((section) => compactText(section)),
    );
    if (scores && scores.length === sections.length) {
      let bestIndex = 0;
      for (let index = 1; index < scores.length; index += 1) {
        if (scores[index] > scores[bestIndex]) {
          bestIndex = index;
        }
      }
      return sections[bestIndex];
    }
  } catch {
    // daemon unavailable — fall through to lexical
  }
  return sections[lexicalBestSectionIndex(prompt, sections)];
}

/**
 * Builds a compact, token-disciplined guidance block from the brain corpus for
 * the detected domains. Used to make Elyan actually apply its design / skill /
 * data language when producing tables, PDFs, reports, and visual output.
 */
export async function buildBrainCorpusGuidanceBlock(
  prompt: string,
  domains: BrainCorpusDomain[],
): Promise<string | null> {
  if (domains.length === 0) {
    return null;
  }
  const orderedDomains = CORPUS_SOURCES.filter((entry) =>
    domains.includes(entry.domain),
  )
    .sort((left, right) => right.priority - left.priority)
    .map((entry) => entry.domain)
    .slice(0, GUIDANCE_DOMAIN_LIMIT);

  const picked: string[] = [];
  for (const domain of orderedDomains) {
    const sections = await loadCorpusSectionsCached(domain);
    const best = await pickBestCorpusSection(prompt, sections);
    if (best) {
      picked.push(best.slice(0, GUIDANCE_SECTION_CHARS).trim());
    }
  }
  if (picked.length === 0) {
    return null;
  }
  return `Elyan brain corpus guidance (apply the relevant points, do not quote this verbatim):\n\n${picked.join("\n\n")}`;
}

export function buildBrainCorpusRetrievalQuery(prompt: string): string {
  const domains = detectBrainCorpusDomains(prompt);
  if (!domains.length) {
    return prompt;
  }

  const taggedContext = CORPUS_SOURCES
    .filter((source) => domains.includes(source.domain))
    .sort((left, right) => right.priority - left.priority)
    .flatMap((source) => [source.domain, source.title, ...source.tags])
    .join(" ");

  return `${prompt}\n\nElyan brain corpus domains: ${taggedContext}`;
}

export async function getBrainCorpusManifest(): Promise<BrainCorpusDocumentManifest[]> {
  return Promise.all(
    CORPUS_SOURCES.map(async (source) => {
      const content = await readCorpusFile(source.fileName);
      return {
        ...source,
        version: ELYAN_BRAIN_CORPUS_VERSION,
        sourceUri: `brain://system-corpus/${ELYAN_BRAIN_CORPUS_VERSION}/${source.fileName}`,
        contentHash: hashText(content),
        characterCount: content.length,
      };
    }),
  );
}

export async function getBrainCorpusReadinessSummary(app: Pick<FastifyInstance, "db">) {
  const result = await app.db.execute(sql`
    select
      kd.metadata->>'elyanCorpusDomain' as "domain",
      kd.metadata->>'elyanCorpusVersion' as "version",
      count(distinct kd.id) as "documents",
      count(kc.id) as "chunks",
      max(kd.updated_at) as "latestUpdatedAt"
    from knowledge_documents kd
    left join knowledge_chunks kc on kc.document_id = kd.id
    where kd.scope = 'shared'
      and kd.status = 'ready'
      and kd.metadata->>'elyanCorpus' = 'true'
    group by kd.metadata->>'elyanCorpusDomain', kd.metadata->>'elyanCorpusVersion'
  `);
  const rows = Array.isArray(result) ? result : (result as { rows?: Array<Record<string, unknown>> }).rows ?? [];

  const categories = rows
    .map((row) => ({
      domain: String(row.domain ?? ""),
      version: String(row.version ?? ""),
      readyDocuments: Number(row.documents ?? 0),
      readyChunks: Number(row.chunks ?? 0),
      latestUpdatedAt: row.latestUpdatedAt instanceof Date ? row.latestUpdatedAt.toISOString() : null,
    }))
    .filter((row) => row.domain && row.version)
    .sort((left, right) => left.domain.localeCompare(right.domain));

  return {
    enabled: true,
    corpusVersion: ELYAN_BRAIN_CORPUS_VERSION,
    expectedDocuments: CORPUS_SOURCES.length,
    readyDocuments: categories.reduce((total, item) => total + item.readyDocuments, 0),
    readyChunks: categories.reduce((total, item) => total + item.readyChunks, 0),
    domains: categories.map((item) => item.domain),
    categories,
  };
}

export async function seedBrainCorpus(app: Pick<FastifyInstance, "db" | "log">) {
  const manifest = await getBrainCorpusManifest();
  const results: Array<{ id: string; domain: BrainCorpusDomain; documentId: string | null; action: "created" | "reused"; chunkCount: number }> = [];

  for (const entry of manifest) {
    const content = await readCorpusFile(entry.fileName);
    const existingRows = await app.db
      .select({
        id: knowledgeDocuments.id,
      })
      .from(knowledgeDocuments)
      .where(
        and(
          eq(knowledgeDocuments.scope, "shared"),
          eq(knowledgeDocuments.contentHash, entry.contentHash),
          eq(knowledgeDocuments.status, "ready"),
        ),
      )
      .limit(1);

    if (existingRows[0]) {
      await indexKnowledgeChunksForDocument(app as FastifyInstance, { documentId: existingRows[0].id }).catch((error) => {
        app.log?.warn?.({ error, corpusId: entry.id }, "brain corpus indexing skipped");
      });
      results.push({
        id: entry.id,
        domain: entry.domain,
        documentId: existingRows[0].id,
        action: "reused",
        chunkCount: 0,
      });
      continue;
    }

    await app.db
      .update(knowledgeDocuments)
      .set({
        status: "archived",
        updatedAt: new Date(),
      })
      .where(
        and(
          eq(knowledgeDocuments.scope, "shared"),
          sql`${knowledgeDocuments.metadata}->>'elyanCorpusId' = ${entry.id}`,
        ),
      );

    const chunks = chunkMarkdown(content);
    const insertedDocuments = await app.db
      .insert(knowledgeDocuments)
      .values({
        ownerUserId: null,
        scope: "shared",
        title: entry.title,
        sourceType: "dataset",
        status: "ready",
        sourceUri: entry.sourceUri,
        contentHash: entry.contentHash,
        summary: compactText(content).slice(0, 700),
        metadata: {
          elyanCorpus: true,
          elyanCorpusId: entry.id,
          elyanCorpusDomain: entry.domain,
          elyanCorpusVersion: entry.version,
          priority: entry.priority,
          tags: entry.tags,
          sourceFile: entry.fileName,
          characterCount: entry.characterCount,
        },
      })
      .returning({
        id: knowledgeDocuments.id,
      });
    const documentId = insertedDocuments[0]?.id;
    if (!documentId) {
      results.push({
        id: entry.id,
        domain: entry.domain,
        documentId: null,
        action: "created",
        chunkCount: 0,
      });
      continue;
    }

    await app.db.insert(knowledgeChunks).values(
      chunks.map((chunk, ordinal) => ({
        documentId,
        ownerUserId: null,
        scope: "shared" as const,
        ordinal,
        content: chunk.content,
        tokenEstimate: chunk.tokenEstimate,
        metadata: {
          ...chunk.metadata,
          elyanCorpus: true,
          elyanCorpusId: entry.id,
          elyanCorpusDomain: entry.domain,
          elyanCorpusVersion: entry.version,
          sourceUri: entry.sourceUri,
        },
      })),
    );

    await indexKnowledgeChunksForDocument(app as FastifyInstance, { documentId }).catch((error) => {
      app.log?.warn?.({ error, corpusId: entry.id }, "brain corpus indexing skipped");
    });
    results.push({
      id: entry.id,
      domain: entry.domain,
      documentId,
      action: "created",
      chunkCount: chunks.length,
    });
  }

  return {
    corpusVersion: ELYAN_BRAIN_CORPUS_VERSION,
    expectedDocuments: manifest.length,
    created: results.filter((item) => item.action === "created").length,
    reused: results.filter((item) => item.action === "reused").length,
    results,
  };
}
