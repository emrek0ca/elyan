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
