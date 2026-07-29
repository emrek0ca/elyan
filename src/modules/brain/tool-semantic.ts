/**
 * Semantic fallback for core tool selection.
 *
 * `scoreCoreToolForTurn` picks tools with hand-written regexes. Those are exact
 * and fast for phrasings someone thought of, and silent for everything else —
 * and a tool that is not selected is never in the catalogue, so the model
 * cannot call it at all. Every missed phrasing therefore reads to the user as
 * "it can't do that", which is the bottomless-pattern-list failure recorded in
 * NEREDE-KALDIK.md §1.
 *
 * This is the core-tool twin of `selectSemanticConnectorReadToolHint`: same
 * ranker, same shape, same reason. Tools are described by what they *do*, so
 * adding a tool teaches the router through its own description instead of
 * through another user-sentence pattern.
 *
 * Two deliberate constraints, both borrowed from the connector path because it
 * already paid for them in production:
 *
 *  - **Negative anchors.** Without something for an off-topic sentence to match
 *    instead, the ranker hands every sentence to its nearest tool — "bugün hava
 *    güzel" scored as a web search in the first cut of this module. The anchors
 *    give ordinary conversation somewhere else to land.
 *  - **Hash fallback disabled.** The degraded lexical embedding matches on token
 *    overlap, not meaning: it misses "ne işe yarıyorsun" vs "neler
 *    yapabiliyorsun" (no shared tokens) while firing on "bugün hava güzel"
 *    (shares "bugün" with a seed). Measured at 1/7 recall with a false positive,
 *    so it is worse than not answering. Transformer or nothing.
 *
 * Read-only tools only. A false positive costs one wasted read; the same
 * mistake on `memory.write` or `goals.update` would mutate user state off a
 * paraphrase nobody verified, so those still require an explicit regex match.
 */

import { rankSemanticTextCandidates } from "../../core/understanding/intent-semantic.js";

export type CoreToolHint = {
  tool: string;
  score: number;
  margin: number;
};

/**
 * What each tool is for, in the user's own terms. Multiple descriptions per
 * tool widen coverage across languages and phrasings without widening the
 * match threshold.
 */
const CORE_TOOL_SEMANTIC_CANDIDATES: Array<{ id: string; description: string }> =
  [
    {
      id: "tool:web.search",
      description:
        "web.search: Güncel bilgi için internette araştırma yap; bir konu, şirket, piyasa veya olay hakkında kaynak topla, son durumu öğren.",
    },
    {
      id: "tool:web.search",
      description:
        "web.search: Search the public web for current information, gather sources about a topic, company, market or event, find out what happened recently.",
    },
    {
      id: "tool:web.fetch_url",
      description:
        "web.fetch_url: Kullanıcının verdiği bir bağlantıyı aç, o sayfadaki içeriği oku ve özetle.",
    },
    {
      id: "tool:web.fetch_url",
      description:
        "web.fetch_url: Open a specific URL the user supplied and read the content of that page.",
    },
    {
      id: "tool:web.numeric_facts",
      description:
        "web.numeric_facts: Sayısal veri serisi, istatistik, fiyat veya oran topla; tabloya ve grafiğe dökülecek rakamları çıkar.",
    },
    {
      id: "tool:web.numeric_facts",
      description:
        "web.numeric_facts: Collect numeric series, statistics, prices or rates suitable for building a table or chart.",
    },
    {
      id: "tool:memory.query",
      description:
        "memory.query: Kullanıcı hakkında daha önce öğrenilenleri hatırla; geçmiş konuşmalarda ne konuşulduğunu, kullanıcının adını, tercihlerini ve verdiği kararları getir.",
    },
    {
      id: "tool:memory.query",
      description:
        "memory.query: Recall what was learned about this user before — their name, preferences, and what was discussed or decided in earlier conversations.",
    },
    {
      id: "tool:goals.get",
      description:
        "goals.get: Kullanıcının açık hedeflerini, planının durumunu ve üzerinde çalıştığı işlerin ilerlemesini göster.",
    },
    {
      id: "tool:goals.get",
      description:
        "goals.get: Show the user's open goals, plan status and progress on what they are currently working towards.",
    },
    {
      id: "tool:system.capabilities",
      description:
        "system.capabilities: Elyan'ın kendi kurulumunu incele — hangi araçları, becerileri ve bağlı entegrasyonları var, neleri yapabiliyor, neye erişebiliyor.",
    },
    {
      id: "tool:system.capabilities",
      description:
        "system.capabilities: Inspect Elyan's own installation — which tools, skills and connected integrations exist, what it is able to do and what it can access.",
    },
  ];

/**
 * Somewhere for ordinary conversation to land. Without these the ranker always
 * returns *some* tool, because the nearest candidate wins by construction.
 */
const CORE_TOOL_SEMANTIC_NEGATIVE_CANDIDATES: Array<{
  id: string;
  description: string;
}> = [
  {
    id: "negative:smalltalk",
    description:
      "Selamlaşma, teşekkür, onay, günlük sohbet; hava durumu yorumu, nezaket cümleleri, 'tamam anladım', 'iyi geceler' gibi araç gerektirmeyen konuşma.",
  },
  {
    id: "negative:smalltalk",
    description:
      "Greetings, thanks, acknowledgements and everyday small talk that needs no tool call.",
  },
  {
    id: "negative:direct_answer",
    description:
      "Doğrudan bilgiyle veya akıl yürütmeyle cevaplanabilecek genel soru; tanım yap, açıkla, çevir, özetle, yeniden yaz, hesapla — dış veri veya kullanıcı geçmişi gerekmez.",
  },
  {
    id: "negative:direct_answer",
    description:
      "A general question answerable from reasoning alone: define, explain, translate, summarise, rewrite or calculate, with no need for external data or user history.",
  },
  {
    id: "negative:write_action",
    description:
      "Bir şey gönder, oluştur, güncelle, sil veya kaydet gibi yan etkili işlem talebi.",
  },
];

/**
 * Calibrated against measured scores, not guessed.
 *
 * e5 similarities for this candidate set sit in a narrow 0.78–0.87 band, so a
 * low threshold makes everything match *something*: at 0.74/0.004 the probe
 * routed "bana dair neler biliyorsun" to `web.fetch_url`, which is worse than
 * not answering because it spends a tool call and misleads the model.
 *
 * Observed separation:
 *   "kripto piyasasını araştır"  web.search 0.8626 (margin 0.029)  ← clear
 *   "hedeflerim ne durumda"      goals.get  0.8680 (margin 0.041)  ← clear
 *   "bana dair neler biliyorsun" negative anchor wins              ← ambiguous
 *   "bugün hava çok güzel"       negative anchor wins              ← small talk
 *
 * These thresholds sit above the ambiguous band on purpose. The layer is built
 * for precision: it rescues paraphrases the regexes clearly missed and declines
 * the rest, leaving them to the deterministic scorer. A miss costs what today
 * already costs; a wrong pick costs trust.
 */
const CORE_TOOL_MIN_SCORE = 0.85;
const CORE_TOOL_MIN_MARGIN = 0.025;

const SEMANTIC_ELIGIBLE_TOOLS: ReadonlySet<string> = new Set(
  CORE_TOOL_SEMANTIC_CANDIDATES.map((candidate) =>
    candidate.id.replace(/^tool:/, ""),
  ),
);

export function isSemanticSelectableTool(name: string): boolean {
  return SEMANTIC_ELIGIBLE_TOOLS.has(name);
}

/**
 * Best semantically-matching core tool for this turn, or null when the prompt
 * is closer to ordinary conversation than to any tool.
 *
 * Async on purpose: the transformer worker is the only signal accurate enough
 * to act on. Callers resolve this once per turn and pass the result into the
 * synchronous catalogue builder, exactly as the connector hint does.
 */
export async function selectSemanticCoreToolHint(
  prompt: string,
  options: { sideEffectDetected?: boolean } = {},
): Promise<CoreToolHint | null> {
  // Topical similarity must not turn a send/create/delete request into a read.
  // This consumes the existing typed risk decision rather than re-reading the
  // sentence here.
  if (options.sideEffectDetected) return null;

  const trimmed = prompt.replace(/\s+/g, " ").trim();
  if (trimmed.length < 3) return null;

  const match = await rankSemanticTextCandidates(
    trimmed,
    [
      ...CORE_TOOL_SEMANTIC_CANDIDATES,
      ...CORE_TOOL_SEMANTIC_NEGATIVE_CANDIDATES,
    ],
    {
      transformerMinScore: CORE_TOOL_MIN_SCORE,
      transformerMinMargin: CORE_TOOL_MIN_MARGIN,
      // Much tighter than the connector path's 20 s. That budget is affordable
      // there because it is only spent on turns that already look like a
      // connector request; this runs on *every* turn, so a slow or cold worker
      // would add its full timeout to each one. Candidate vectors are cached
      // per text, so the steady-state cost is one query embed (~3 ms) and this
      // ceiling only bounds the cold path.
      transformerTimeoutMs: 1_500,
      // The lexical approximation is measurably wrong here (see module header);
      // these thresholds are unreachable, so hash mode never decides.
      hashMinScore: 1.1,
      hashMinMargin: 1.1,
    },
  ).catch(() => null);

  if (!match || match.source !== "transformer") return null;
  if (!match.id.startsWith("tool:")) return null;

  return {
    tool: match.id.slice("tool:".length),
    score: match.score,
    margin: match.margin,
  };
}

/**
 * Confidence for a semantically-selected tool. Capped below what an explicit
 * regex hit earns so a deterministic match still outranks an inferred one.
 */
export function semanticToolConfidence(score: number): number {
  const span = Math.max(1e-6, 1 - CORE_TOOL_MIN_SCORE);
  const ratio = Math.min(1, Math.max(0, (score - CORE_TOOL_MIN_SCORE) / span));
  // Floor sits just above the catalogue's 0.72 admission threshold; the ceiling
  // stays under an explicit regex hit so deterministic matches still rank first.
  return Number((0.74 + ratio * 0.14).toFixed(4));
}
