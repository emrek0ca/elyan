import { createHash } from 'crypto';
import { mkdir, readFile, writeFile } from 'fs/promises';
import * as cheerio from 'cheerio';
import {
  ingestRetrievalText,
  loadTextFromSource,
  normalizeRetrievalText,
  truncateRetrievalText,
} from '@/core/retrieval';

export type BootstrapDatasetName =
  | 'common_crawl'
  | 'c4'
  | 'redpajama'
  | 'the_pile'
  | 'openwebtext'
  | string;

export type BootstrapManifestSource = {
  dataset: BootstrapDatasetName;
  sourceName?: string;
  url?: string;
  path?: string;
  title?: string;
  language?: string;
  maxChunks?: number;
  chunkSize?: number;
  overlap?: number;
  metadata?: Record<string, unknown>;
};

export type BootstrapManifest = {
  sources: BootstrapManifestSource[];
  chunkSize?: number;
  overlap?: number;
  maxChunksPerSource?: number;
};

export type BootstrapChunkRecord = {
  dataset: BootstrapDatasetName;
  source_name: string;
  source_url?: string;
  title?: string;
  chunk_index: number;
  content: string;
  content_hash: string;
  metadata: Record<string, unknown>;
};

export type BootstrapBuildResult = {
  records: BootstrapChunkRecord[];
  summary: {
    source_count: number;
    chunk_count: number;
    dataset_counts: Record<string, number>;
    created_at: string;
  };
};

function isHtmlDocument(text: string) {
  return /<html[\s>]/i.test(text) || /<body[\s>]/i.test(text) || /<div[\s>]/i.test(text);
}

function cleanHtml(text: string) {
  const $ = cheerio.load(text);
  $('script,style,noscript,iframe,svg,canvas').remove();
  return normalizeRetrievalText(
    $('body')
      .text()
      .replace(/\n{3,}/g, '\n\n')
  );
}

export function cleanBootstrapText(text: string) {
  const normalized = normalizeRetrievalText(text);
  return truncateRetrievalText(isHtmlDocument(normalized) ? cleanHtml(normalized) : normalized, 16_000);
}

export function chunkBootstrapText(text: string, chunkSize = 1_400, overlap = 160) {
  const chunks: string[] = [];
  const normalized = cleanBootstrapText(text);
  if (!normalized) {
    return chunks;
  }

  let cursor = 0;
  while (cursor < normalized.length) {
    const end = Math.min(normalized.length, cursor + chunkSize);
    const chunk = normalized.slice(cursor, end).trim();
    if (chunk) {
      chunks.push(chunk);
    }

    if (end >= normalized.length) {
      break;
    }

    cursor = Math.max(end - overlap, cursor + 1);
  }

  return chunks;
}

function createChunkHash(input: { dataset: string; sourceName: string; chunkIndex: number; content: string }) {
  return createHash('sha256')
    .update(JSON.stringify({
      dataset: input.dataset,
      sourceName: input.sourceName,
      chunkIndex: input.chunkIndex,
      content: input.content,
    }))
    .digest('hex');
}

async function readManifest(manifestPath: string) {
  const raw = await readFile(manifestPath, 'utf8');
  return JSON.parse(raw) as BootstrapManifest;
}

async function writeJson(pathname: string, payload: unknown) {
  await writeFile(pathname, `${JSON.stringify(payload, null, 2)}\n`, 'utf8');
}

async function writeJsonl(pathname: string, records: BootstrapChunkRecord[]) {
  const content = records.map((record) => JSON.stringify(record)).join('\n');
  await writeFile(pathname, `${content}${content.length > 0 ? '\n' : ''}`, 'utf8');
}

export async function buildBootstrapRecords(manifest: BootstrapManifest): Promise<BootstrapBuildResult> {
  const records: BootstrapChunkRecord[] = [];
  const seenHashes = new Set<string>();
  const datasetCounts: Record<string, number> = {};
  const sources = Array.isArray(manifest.sources) ? manifest.sources : [];

  for (const source of sources) {
    const rawText = await loadTextFromSource({ url: source.url, path: source.path });
    const chunks = chunkBootstrapText(rawText, source.chunkSize ?? manifest.chunkSize ?? 1_400, source.overlap ?? manifest.overlap ?? 160);
    const limitedChunks = chunks.slice(0, Math.max(1, source.maxChunks ?? manifest.maxChunksPerSource ?? 20));

    for (const [index, content] of limitedChunks.entries()) {
      const sourceName = source.sourceName ?? source.dataset;
      const chunkRecord = {
        dataset: source.dataset,
        source_name: sourceName,
        source_url: source.url,
        title: source.title ?? sourceName,
        chunk_index: index,
        content,
        content_hash: createChunkHash({
          dataset: source.dataset,
          sourceName,
          chunkIndex: index,
          content,
        }),
        metadata: {
          dataset: source.dataset,
          language: source.language ?? 'unknown',
          ...source.metadata,
        },
      };

      if (seenHashes.has(chunkRecord.content_hash)) {
        continue;
      }

      seenHashes.add(chunkRecord.content_hash);
      datasetCounts[source.dataset] = (datasetCounts[source.dataset] ?? 0) + 1;
      records.push(chunkRecord);

      await ingestRetrievalText({
        sourceKind: 'bootstrap',
        sourceName: sourceName,
        sourceUrl: source.url,
        title: source.title ?? sourceName,
        content,
        metadata: chunkRecord.metadata,
      });
    }
  }

  return {
    records,
    summary: {
      source_count: sources.length,
      chunk_count: records.length,
      dataset_counts: datasetCounts,
      created_at: new Date().toISOString(),
    },
  };
}

export async function runBootstrapPipeline(manifestPath: string, outputDir: string) {
  const manifest = await readManifest(manifestPath);
  const build = await buildBootstrapRecords(manifest);
  await mkdir(outputDir, { recursive: true });

  await Promise.all([
    writeJson(`${outputDir}/bootstrap-manifest.json`, manifest),
    writeJson(`${outputDir}/bootstrap-summary.json`, build.summary),
    writeJsonl(`${outputDir}/bootstrap-records.jsonl`, build.records),
  ]);

  return {
    ok: true,
    manifest_path: manifestPath,
    output_dir: outputDir,
    ...build.summary,
  };
}
