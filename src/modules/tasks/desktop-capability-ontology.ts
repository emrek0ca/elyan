import {
  DESKTOP_CAPABILITY_MANIFEST,
  type DesktopCapabilityManifestEntry,
} from "./desktop-capability-manifest.js";

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

const EMBEDDING_BUCKETS = 512;
const ontologyCache = new Map<string, DesktopCapabilityOntologyEntry[]>();
const embeddingCache = new Map<string, SparseEmbedding>();

const CURATED_ALIASES: Record<string, string[]> = {
  analyze_screen: [
    "ekranda ne var",
    "ekrani oku",
    "aktif pencereyi analiz et",
    "visible error",
    "screen analysis",
  ],
  browser_control: [
    "chrome ac",
    "tarayicida ac",
    "tarayicidan bak",
    "siteye gir",
    "linki ac",
    "webde bul",
    "internet ara",
    "google'da ara",
    "open website",
    "open url",
    "search web",
  ],
  "browser_agent.run": [
    "tarayicida adim adim yap",
    "form doldur",
    "sayfayi gez ve tamamla",
    "browser automation",
  ],
  directory_tree: [
    "klasor agaci",
    "klasorleri listele",
    "dosya yapisini goster",
  ],
  document_read: [
    "belge oku",
    "pdf oku",
    "docx oku",
    "dosyayi ozetle",
    "document parse",
  ],
  document_write: [
    "belge yaz",
    "docx olustur",
    "pdf hazirla",
    "pdf rapor hazirla",
    "masaustune pdf rapor kaydet",
    "rapor kaydet",
    "document export",
  ],
  file_read: [
    "dosya oku",
    "yerel dosyayi ac",
    "file read",
    "filesystem read",
  ],
  file_search: [
    "dosya ara",
    "klasorde bul",
    "find local file",
    "recent file search",
  ],
  file_write: [
    "dosyaya yaz",
    "file write",
    "kaydet",
    "write local file",
  ],
  file_move: [
    "dosya tasi",
    "dosyayi yeniden adlandir",
    "move file",
    "rename file",
  ],
  image_generate: [
    "gorsel uret",
    "resim ciz",
    "image generate",
    "draw picture",
  ],
  image_edit: [
    "gorseli duzenle",
    "resme ekle",
    "image edit",
    "modify image",
  ],
  open_app: [
    "uygulama ac",
    "chrome'u ac",
    "finder ac",
    "open app",
  ],
  close_app: [
    "uygulama kapat",
    "chrome'u kapat",
    "close app",
  ],
  "desktop_operator.observe_screen": [
    "ekrani gozlemle",
    "screenshot al",
    "screen observe",
  ],
  "desktop_operator.run": [
    "masaustunde isi yap",
    "tikla yaz kaydir",
    "bilgisayarda uygula",
    "desktop task",
    "computer control",
  ],
  presentation_write: [
    "sunum hazirla",
    "slayt olustur",
    "pptx yap",
    "presentation create",
  ],
  spreadsheet_write: [
    "excel hazirla",
    "tablo olustur",
    "xlsx yap",
    "spreadsheet create",
  ],
  shell_run: [
    "terminal komutu calistir",
    "shell run",
    "script calistir",
  ],
  web_research: [
    "web arastir",
    "kaynak topla",
    "internet kaynaklari",
    "public research",
  ],
};

const CURATED_NEGATIVES: Record<string, string[]> = {
  browser_control: [
    "sadece web arastirmasi raporu yaz",
    "tarayici hakkinda bilgi ver",
  ],
  document_write: [
    "belge nasil yazilir anlat",
    "pdf nedir acikla",
  ],
  file_write: [
    "dosyaya yazmadan oner",
    "kaydetme sadece anlat",
  ],
  "desktop_operator.run": [
    "masaustu uygulamalari hakkinda tavsiye ver",
    "bilgisayarda yapmadan planla",
  ],
  web_research: [
    "tarayicida siteyi ac",
    "yerel dosyada ara",
  ],
};

function normalizeText(value: string): string {
  return value
    .toLocaleLowerCase("tr-TR")
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
    /\b(delete|remove|erase|sil|kaldir|destructive)\b/u.test(text) ||
    name.includes("delete")
  ) {
    return "destructive";
  }
  if (
    entry.privacyClass.includes("_read") ||
    entry.privacyClass.includes("screen") ||
    /\b(read|search|list|status|observe|analyze|oku|ara|listele|gozlemle|analiz)\b/u.test(
      text,
    )
  ) {
    return "read";
  }
  if (
    entry.privacyClass.includes("_write") ||
    /\b(write|send|add|save|move|patch|commit|create|update|edit|yaz|gonder|ekle|kaydet|tasi|olustur|duzenle)\b/u.test(
      text,
    )
  ) {
    return "write";
  }
  return "none";
}

function runtimeNamesFor(name: string): string[] {
  const dotted = name.replaceAll("_", ".");
  const underscored = name.replaceAll(".", "_");
  return [...new Set([name, dotted, underscored])];
}

function examplesFromFewShots(
  fewShots: DesktopCapabilityManifestEntry["fewShots"],
): string[] {
  return fewShots
    .map((shot) => JSON.stringify(shot))
    .filter((shot) => shot.length > 2)
    .slice(0, 4);
}

export function getDesktopCapabilityOntology(): DesktopCapabilityOntologyEntry[] {
  const cached = ontologyCache.get("v1");
  if (cached) return cached;
  const entries = DESKTOP_CAPABILITY_MANIFEST.map((entry) => {
    const aliases = [
      entry.name,
      entry.displayName,
      ...runtimeNamesFor(entry.name),
      ...(CURATED_ALIASES[entry.name] ?? []),
      ...entry.skillAffinity,
    ];
    const examples = [
      entry.description,
      entry.usage,
      ...entry.whenToUse,
      ...entry.verificationPlan,
      ...examplesFromFewShots(entry.fewShots),
    ];
    const negativeExamples = [
      ...entry.whenNotToUse,
      ...(CURATED_NEGATIVES[entry.name] ?? []),
    ];
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

function ontologyEntryText(entry: DesktopCapabilityOntologyEntry): string {
  return [
    entry.canonicalId,
    ...entry.aliases,
    ...entry.examples,
    entry.privacyClass,
    entry.sideEffectClass,
  ].join(" ");
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
  const queryEmbedding = embedText(query);
  const intent = input.intent ?? "";
  const matches = getDesktopCapabilityOntology()
    .map((entry) => {
      const positive = cosine(queryEmbedding, embedText(ontologyEntryText(entry)));
      const negative =
        entry.negativeExamples.length > 0
          ? Math.max(
              ...entry.negativeExamples.map((example) =>
                cosine(queryEmbedding, embedText(example)),
              ),
            )
          : 0;
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
      return {
        capability: entry.canonicalId,
        score: Number(
          Math.max(0, positive + intentBoost - negative * 0.5 - sideEffectPenalty).toFixed(
            4,
          ),
        ),
        entry,
      };
    })
    .filter((match) => match.score >= (input.threshold ?? 0.18))
    .sort((left, right) => right.score - left.score || left.capability.localeCompare(right.capability));
  return matches.slice(0, input.limit ?? 8);
}
