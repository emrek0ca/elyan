import { fetchFactJson, readRecord } from "../http.js";
import { defineFactProvider, type FactAnswer } from "../types.js";
import { collapseWhitespace as compactText } from "../../../lib/text.js";

type CrossrefParams = { query: string };

function publishedDate(item: Record<string, unknown>): string | null {
  for (const key of ["published", "published-print", "published-online", "issued"]) {
    const record = readRecord(item[key]);
    const parts = Array.isArray(record?.["date-parts"])
      ? record?.["date-parts"]
      : [];
    const date = Array.isArray(parts[0]) ? parts[0].map(Number) : [];
    if (!date[0]) continue;
    return `${date[0]}-${String(date[1] ?? 1).padStart(2, "0")}-${String(date[2] ?? 1).padStart(2, "0")}`;
  }
  return null;
}

export const crossrefProvider = defineFactProvider<CrossrefParams>({
  id: "crossref",
  dataClass: "daily",
  authority: "Crossref",
  commercialUse: "allowed",
  allowStale: true,
  units: ["publication"],
  timeoutMs: 1_500,
  ttlMs: 6 * 60 * 60_000,
  intents: [
    "bu konuda akademik yayın bul",
    "makalenin DOI numarası nedir",
    "son bilimsel çalışmaları getir",
    "yayının yazarları kim",
    "find peer reviewed papers",
  ],
  extract(prompt) {
    const query = compactText(prompt).slice(0, 240);
    return query ? { query } : null;
  },
  cacheKey(params) {
    return `crossref:${params.query.toLowerCase()}`;
  },
  async resolve(context, params): Promise<FactAnswer | null> {
    const url = new URL("https://api.crossref.org/works");
    url.searchParams.set("query.bibliographic", params.query);
    url.searchParams.set("rows", "3");
    if (context.secrets.crossrefMailto) {
      url.searchParams.set("mailto", context.secrets.crossrefMailto);
    }
    const payload = readRecord(
      await fetchFactJson({
        providerId: "crossref",
        url: url.toString(),
        timeoutMs: context.timeoutMs,
        maxBytes: 500_000,
      }),
    );
    const message = readRecord(payload?.message);
    const items = Array.isArray(message?.items) ? message.items : [];
    const papers = items.flatMap((entry) => {
      const item = readRecord(entry);
      if (!item) return [];
      const title = Array.isArray(item.title)
        ? compactText(item.title[0])
        : compactText(item.title);
      const doi = compactText(item.DOI);
      const authors = Array.isArray(item.author)
        ? item.author
            .slice(0, 4)
            .map((author) => readRecord(author))
            .map((author) => compactText(`${author?.given ?? ""} ${author?.family ?? ""}`))
            .filter(Boolean)
        : [];
      const date = publishedDate(item);
      return title && doi ? [{ title, doi, authors, publishedAt: date }] : [];
    });
    const first = papers[0];
    if (!first) return null;
    const indexed = readRecord(readRecord(items[0])?.indexed);
    const observedAt = new Date(String(indexed?.["date-time"] ?? Date.now())).toISOString();
    return {
      providerId: "crossref",
      dataClass: "daily",
      snippet: papers
        .map((paper) => `${paper.title}; DOI ${paper.doi}; ${paper.publishedAt ?? "tarih yok"}; ${paper.authors.join(", ")}`)
        .join(" | ")
        .slice(0, 2_500),
      directAnswer: `${first.title}${first.publishedAt ? ` (${first.publishedAt})` : ""}. DOI: ${first.doi}.`,
      citation: {
        title: first.title,
        url: `https://doi.org/${first.doi}`,
        sourceHost: "api.crossref.org",
        observedAt,
      },
      values: { papers },
      confidence: 0.94,
      ttlMs: 6 * 60 * 60_000,
    };
  },
});
