import { spawn, type ChildProcess } from "node:child_process";
import { createInterface } from "node:readline";
import { existsSync } from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const DEFAULT_BIN = path.resolve(__dirname, "../../bin/elyan_nlp");

type NlpRequest = Record<string, unknown> & { type: string };

interface NlpResponse {
  ok: boolean;
  _id?: string;
  [key: string]: unknown;
}

interface PendingRequest {
  resolve: (value: NlpResponse) => void;
  reject:  (reason: Error)      => void;
  timer:   ReturnType<typeof setTimeout>;
}

const REQUEST_TIMEOUT_MS = 2_500;

const CONTROL_AND_ZERO_WIDTH_FALLBACK =
  /[\u0000-\u0008\u000B\u000C\u000E-\u001F\u007F-\u009F\u200B-\u200F\u202A-\u202E\u2066-\u2069\uFEFF]/g;

function normalizeTextFallback(text: string): { text: string; modified: boolean } {
  const original = String(text ?? "");
  const normalized = original
    .replace(CONTROL_AND_ZERO_WIDTH_FALLBACK, "")
    .replace(/\s+/g, " ")
    .trim();
  return {
    text: normalized,
    modified: normalized !== original.trim(),
  };
}

function tokenizeRetrievalFallback(text: string, limit = 120): string[] {
  // i-ailesi collapse (İ/I/ı → i) — C tokenize_retrieval ile parity.
  const normalized = normalizeTextFallback(text)
    .text.replace(/İ|I/g, "i")
    .toLowerCase()
    .replace(/ı/g, "i");
  const matches = normalized.match(/[a-z0-9çğıöşü_.-]{2,}/giu) ?? [];
  return matches.slice(0, Math.max(1, Math.min(limit, 512)));
}

export class NlpDaemon {
  private proc:      ChildProcess | null = null;
  private pending:   Map<string, PendingRequest> = new Map();
  private counter    = 0;
  private available  = false;
  private readonly binPath: string;

  constructor(binPath?: string) {
    this.binPath = binPath ?? process.env.ELYAN_NLP_BIN ?? DEFAULT_BIN;
  }

  start(logger?: { info: (msg: string) => void; warn: (msg: string) => void }): void {
    if (!existsSync(this.binPath)) {
      logger?.warn(`[nlp-daemon] binary not found at ${this.binPath} — running without C NLP`);
      return;
    }
    this._spawn(logger);
  }

  private _spawn(logger?: { info: (msg: string) => void; warn: (msg: string) => void }): void {
    try {
      const child = spawn(this.binPath, [], {
        stdio: ["pipe", "pipe", "ignore"],
      });

      if (!child.stdout || !child.stdin) {
        logger?.warn("[nlp-daemon] failed to open stdio streams");
        child.kill();
        return;
      }

      this.proc = child;

      const rl = createInterface({ input: child.stdout, crlfDelay: Infinity });
      rl.on("line", (line) => this._onLine(line));

      child.on("error", (err) => {
        logger?.warn(`[nlp-daemon] spawn error: ${err.message}`);
        this._shutdown();
      });

      child.on("exit", (code) => {
        logger?.warn(`[nlp-daemon] process exited (code=${code}) — disabling C NLP`);
        this._shutdown();
      });

      child.stdin.on("error", (err) => {
        logger?.warn(`[nlp-daemon] stdin error: ${err.message} — disabling C NLP`);
        this._shutdown();
      });

      this.available = true;
      logger?.info("[nlp-daemon] C NLP core online");
    } catch (err) {
      logger?.warn(`[nlp-daemon] failed to start: ${String(err)}`);
      this.available = false;
    }
  }

  private _shutdown(): void {
    this.available = false;
    this.proc = null;
    for (const [id, req] of this.pending) {
      clearTimeout(req.timer);
      req.reject(new Error("nlp_daemon_died"));
      this.pending.delete(id);
    }
  }

  private _onLine(line: string): void {
    let resp: NlpResponse;
    try {
      resp = JSON.parse(line) as NlpResponse;
    } catch {
      return;
    }
    const id = resp._id ?? "";
    const pending = this.pending.get(id);
    if (pending) {
      clearTimeout(pending.timer);
      this.pending.delete(id);
      pending.resolve(resp);
    }
  }

  private _send(req: NlpRequest): Promise<NlpResponse> {
    return new Promise((resolve, reject) => {
      if (!this.available || !this.proc) {
        reject(new Error("nlp_daemon_unavailable"));
        return;
      }

      const id    = String(++this.counter);
      const json  = JSON.stringify({ ...req, _id: id }) + "\n";
      const timer = setTimeout(() => {
        if (this.pending.has(id)) {
          this.pending.delete(id);
          reject(new Error("nlp_daemon_timeout"));
        }
      }, REQUEST_TIMEOUT_MS);

      this.pending.set(id, { resolve, reject, timer });

      const stdin = this.proc.stdin;
      if (!stdin) {
        clearTimeout(timer);
        this.pending.delete(id);
        reject(new Error("nlp_daemon_no_stdin"));
        return;
      }

      stdin.write(json, (err) => {
        if (err) {
          clearTimeout(timer);
          this.pending.delete(id);
          reject(err);
        }
      });
    });
  }

  /* ── Public API ─────────────────────────────────────────── */

  isAvailable(): boolean {
    return this.available;
  }

  async ping(): Promise<boolean> {
    try {
      const r = await this._send({ type: "ping" });
      return r.ok === true;
    } catch {
      return false;
    }
  }

  async tokenize(text: string): Promise<string[]> {
    try {
      const r = await this._send({ type: "tokenize", text });
      return Array.isArray(r.tokens) ? (r.tokens as string[]) : [];
    } catch {
      return [];
    }
  }

  async normalizeText(text: string): Promise<{ text: string; modified: boolean }> {
    const fallback = normalizeTextFallback(text);
    try {
      const r = await this._send({ type: "normalize_text", text });
      if (typeof r.text !== "string") return fallback;
      return {
        text: r.text,
        modified: typeof r.modified === "boolean" ? r.modified : r.text !== String(text ?? "").trim(),
      };
    } catch {
      return fallback;
    }
  }

  async tokenizeRetrieval(text: string, limit = 120): Promise<string[]> {
    try {
      const r = await this._send({ type: "tokenize_retrieval", text });
      const tokens = Array.isArray(r.tokens)
        ? (r.tokens as unknown[]).filter((token): token is string => typeof token === "string")
        : [];
      return tokens.slice(0, Math.max(1, Math.min(limit, 512)));
    } catch {
      return tokenizeRetrievalFallback(text, limit);
    }
  }

  async scoreBm25(query: string, doc: string, avgLen = 20): Promise<number | null> {
    try {
      const r = await this._send({ type: "score_bm25", query, doc, avg_len: String(avgLen) });
      return typeof r.score === "number" ? r.score : null;
    } catch {
      return null;
    }
  }

  async extractFacts(text: string): Promise<Array<{ k: string; v: string; c: number }>> {
    try {
      const r = await this._send({ type: "extract_facts", text });
      if (!Array.isArray(r.facts)) return [];
      return (r.facts as Array<unknown>).filter(
        (f): f is { k: string; v: string; c: number } =>
          typeof f === "object" && f !== null &&
          typeof (f as Record<string, unknown>).k === "string" &&
          typeof (f as Record<string, unknown>).v === "string",
      );
    } catch {
      return [];
    }
  }

  async deriveHints(signal: {
    kind: string;
    summary: string;
    energy?:      string | null;
    readiness?:   number | null;
    mobility?:    string | null;
    busyness?:    string | null;
    attention?:   string | null;
    city?:        string | null;
    freeMinutes?: number | null;
  }): Promise<Array<{ hint: string; bucket: string; w: number }>> {
    try {
      const req: NlpRequest = {
        type:        "derive_hints",
        kind:        signal.kind,
        summary:     signal.summary,
        energy:      signal.energy      ?? "",
        mobility:    signal.mobility    ?? "",
        busyness:    signal.busyness    ?? "",
        attention:   signal.attention   ?? "",
        city:        signal.city        ?? "",
        readiness:   signal.readiness   != null ? String(signal.readiness)   : "",
        freeMinutes: signal.freeMinutes != null ? String(signal.freeMinutes) : "",
      };
      const r = await this._send(req);
      if (!Array.isArray(r.hints)) return [];
      return (r.hints as Array<unknown>).filter(
        (h): h is { hint: string; bucket: string; w: number } =>
          typeof h === "object" && h !== null &&
          typeof (h as Record<string, unknown>).hint === "string" &&
          typeof (h as Record<string, unknown>).bucket === "string",
      );
    } catch {
      return [];
    }
  }

  async classifyIntent(text: string): Promise<string> {
    try {
      const r = await this._send({ type: "classify_intent", text });
      return typeof r.intent === "string" ? r.intent : "general";
    } catch {
      return "general";
    }
  }

  /** SHA-256 hash embedding (256 dims) — identical to buildHashedKnowledgeEmbedding() */
  async embed256(text: string): Promise<number[] | null> {
    try {
      const r = await this._send({ type: "embed_256", text });
      if (!Array.isArray(r.vector)) return null;
      return r.vector as number[];
    } catch {
      return null;
    }
  }

  /** Cosine similarity between two equal-length float vectors */
  async cosineSim(a: number[], b: number[]): Promise<number | null> {
    try {
      const r = await this._send({ type: "cosine_sim", a, b });
      return typeof r.score === "number" ? r.score : null;
    } catch {
      return null;
    }
  }

  /**
   * Score N documents against a single query in one IPC round-trip.
   * Returns scores in the same order as docs[].
   */
  async bm25Batch(query: string, docs: string[], avgLen = 20): Promise<number[] | null> {
    if (!docs.length) return [];
    try {
      const r = await this._send({ type: "bm25_batch", query, docs, avg_len: String(avgLen) });
      if (!Array.isArray(r.scores)) return null;
      return r.scores as number[];
    } catch {
      return null;
    }
  }

  /**
   * Lexical overlap batch — memory.ts lexicalOverlapScore'un C karşılığı.
   * Tek IPC çağrısında N doküman skorlanır; daemon yoksa null döner ve
   * çağıran JS fallback'ini kullanır.
   */
  async overlapBatch(query: string, docs: string[]): Promise<number[] | null> {
    if (!docs.length) return [];
    try {
      const r = await this._send({ type: "overlap_batch", query, docs });
      if (!Array.isArray(r.scores) || r.scores.length !== docs.length) return null;
      return r.scores as number[];
    } catch {
      return null;
    }
  }

  /** Keyword-based sentiment analysis — no LLM required. */
  async scoreSentiment(text: string): Promise<{ label: "positive" | "negative" | "neutral" | "mixed"; score: number; positive: number; negative: number } | null> {
    try {
      const r = await this._send({ type: "score_sentiment", text });
      if (typeof r.label !== "string") return null;
      return {
        label:    r.label    as "positive" | "negative" | "neutral" | "mixed",
        score:    typeof r.score    === "number" ? r.score    : 0.5,
        positive: typeof r.positive === "number" ? r.positive : 0,
        negative: typeof r.negative === "number" ? r.negative : 0,
      };
    } catch {
      return null;
    }
  }

  /** Detect language of text — returns "tr", "en", or "mixed" with confidence. */
  async detectLanguage(text: string): Promise<{ lang: "tr" | "en" | "mixed"; confidence: number } | null> {
    try {
      const r = await this._send({ type: "detect_language", text });
      if (typeof r.lang !== "string") return null;
      return {
        lang:       r.lang       as "tr" | "en" | "mixed",
        confidence: typeof r.confidence === "number" ? r.confidence : 0.5,
      };
    } catch {
      return null;
    }
  }

  /** Extract top-N keywords from text — useful for memory tagging. */
  async extractKeywords(text: string, topN = 8): Promise<string[]> {
    try {
      const r = await this._send({ type: "extract_keywords", text, topN: String(topN) });
      return Array.isArray(r.keywords) ? (r.keywords as string[]) : [];
    } catch {
      return [];
    }
  }

  /**
   * Per-plan token bucket rate check — in-process, zero DB.
   * Returns allowed=true and consumes one token, or allowed=false with retryAfterMs.
   */
  async rateCheck(userId: string, plan: string): Promise<{ allowed: boolean; retryAfterMs: number }> {
    try {
      const r = await this._send({ type: "rate_check", userId, plan });
      return {
        allowed:      r.allowed === true,
        retryAfterMs: typeof r.retryAfterMs === "number" ? r.retryAfterMs : 0,
      };
    } catch {
      return { allowed: true, retryAfterMs: 0 };
    }
  }

  async rateCheckV2(input: {
    identity: string;
    plan: string;
    scope: string;
    costWeight?: number;
  }): Promise<{ allowed: boolean; retryAfterMs: number; capacity: number; ratePerMinute: number } | null> {
    try {
      const r = await this._send({
        type: "rate_check_v2",
        identity: input.identity,
        plan: input.plan,
        scope: input.scope,
        costWeight: String(input.costWeight ?? 1),
      });
      return {
        allowed: r.allowed === true,
        retryAfterMs: typeof r.retryAfterMs === "number" ? r.retryAfterMs : 0,
        capacity: typeof r.capacity === "number" ? r.capacity : 0,
        ratePerMinute: typeof r.ratePerMinute === "number" ? r.ratePerMinute : 0,
      };
    } catch {
      return null;
    }
  }

  async abuseScore(input: {
    text: string;
    scope: string;
    plan: string;
    hasAuth: boolean;
    hasDevice: boolean;
    costWeight?: number;
  }): Promise<{ score: number; signals: string[] } | null> {
    try {
      const r = await this._send({
        type: "abuse_score",
        text: input.text,
        scope: input.scope,
        plan: input.plan,
        hasAuth: input.hasAuth ? "1" : "0",
        hasDevice: input.hasDevice ? "1" : "0",
        costWeight: String(input.costWeight ?? 1),
      });
      if (typeof r.score !== "number") return null;
      return {
        score: Math.max(0, Math.min(1, r.score)),
        signals: Array.isArray(r.signals) ? (r.signals as string[]).filter((value) => typeof value === "string") : [],
      };
    } catch {
      return null;
    }
  }

  /** Fast token count estimate — same formula as estimateTextTokens(), no LLM. */
  async estimateTokens(text: string): Promise<{ tokens: number; chars: number } | null> {
    try {
      const r = await this._send({ type: "estimate_tokens", text });
      if (typeof r.tokens !== "number") return null;
      return {
        tokens: r.tokens as number,
        chars:  typeof r.chars === "number" ? r.chars as number : 0,
      };
    } catch {
      return null;
    }
  }

  /** Measure text complexity — for calibrating response verbosity. */
  async scoreComplexity(text: string): Promise<{ avgSentenceLen: number; vocabRichness: number; tokenCount: number; sentenceCount: number } | null> {
    try {
      const r = await this._send({ type: "score_complexity", text });
      if (typeof r.tokenCount !== "number") return null;
      return {
        avgSentenceLen: typeof r.avgSentenceLen === "number" ? r.avgSentenceLen : 0,
        vocabRichness:  typeof r.vocabRichness  === "number" ? r.vocabRichness  : 0,
        tokenCount:     typeof r.tokenCount     === "number" ? r.tokenCount     : 0,
        sentenceCount:  typeof r.sentenceCount  === "number" ? r.sentenceCount  : 0,
      };
    } catch {
      return null;
    }
  }

  /**
   * Selects chunk IDs that fit within charBudget (edge-boosted greedy).
   * Returns null on error (fail-open → caller uses its own fallback).
   */
  async chunkBudget(
    chunks: Array<{ id: string; charCount: number; position?: number }>,
    budgetChars: number,
  ): Promise<string[] | null> {
    try {
      const r = await this._send({ type: "chunk_budget", chunks, budgetChars });
      return Array.isArray(r.selected) ? (r.selected as string[]) : null;
    } catch {
      return null;
    }
  }

  /**
   * Strips Turkish/English stopwords from a search query.
   * Returns the original query on error (fail-open).
   */
  async cleanSearchQuery(query: string): Promise<string> {
    try {
      const r = await this._send({ type: "clean_search_query", query });
      return typeof r.query === "string" && r.query.length > 0 ? r.query : query;
    } catch {
      return query;
    }
  }

  stop(): void {
    this.available = false;
    try { this.proc?.stdin?.end(); } catch {}
    try { this.proc?.kill("SIGTERM"); } catch {}
    this.proc = null;
    for (const [, req] of this.pending) {
      clearTimeout(req.timer);
      req.reject(new Error("nlp_daemon_stopped"));
    }
    this.pending.clear();
  }
}

export const nlpDaemon = new NlpDaemon();
