import { createHash } from "node:crypto";
import { isExplicitMathSurface3DRequest } from "../../core/understanding/structured-output-policy.js";
import type { SharedBrainWorkload } from "./workloads.js";
import type {
  MathSurface3DBlock,
  SharedBrainInferenceInput,
  SharedBrainInferenceResult,
} from "./inference.js";

/**
 * 3B matematik yüzeyi — ifade ayrıştırma, güvenlik denetimi ve blok kurma.
 *
 * `brain/inference.ts` içinden ÇIKARILDI. Taşıma saf: tek satır mantık
 * değişmedi. Dokuz fonksiyonun tamamı yalnız birbirini çağırıyor ve dışarıya
 * tek giriş veriyor (`buildMathSurface3DResult`); kalan dosya sağlayıcı
 * yönetimi ve tur akışıyken bu küme matematik ifadesi ayrıştırıyor.
 *
 * Tipler `inference.ts`ten `import type` ile alınır — tip içe aktarımı
 * derleme sonrası silinir, bu yüzden çalışma zamanında döngü oluşmaz.
 */

const mathSurfaceAllowedIdentifierSet = new Set([
  "x",
  "y",
  "sin",
  "cos",
  "tan",
  "exp",
  "log",
  "sqrt",
  "abs",
]);

const defaultMathSurfacePolynomialExpression = "x^3 - 3*x*y^2 + 3*x^2*y - y^3";

function normalizeMathSurfaceExpression(raw: string): string {
  const expanded = expandMathSurfaceSuperscripts(raw)
    .replace(/[−–—]/g, "-")
    .replace(/\*\*/g, "^")
    .replace(/^\s*z\s*=\s*/i, "")
    .trim();
  return insertMathSurfaceImplicitMultiplication(expanded);
}

function expandMathSurfaceSuperscripts(raw: string): string {
  const superscriptDigits: Record<string, string> = {
    "⁰": "0",
    "¹": "1",
    "²": "2",
    "³": "3",
    "⁴": "4",
    "⁵": "5",
    "⁶": "6",
    "⁷": "7",
    "⁸": "8",
    "⁹": "9",
    "⁻": "-",
  };
  let out = "";
  let pendingPower = "";
  const flushPower = () => {
    if (!pendingPower) return;
    out += `^${pendingPower}`;
    pendingPower = "";
  };
  for (const char of String(raw ?? "")) {
    const mapped = superscriptDigits[char];
    if (mapped !== undefined) {
      pendingPower += mapped;
      continue;
    }
    flushPower();
    out += char;
  }
  flushPower();
  return out;
}

type MathSurfaceToken =
  | { kind: "number"; value: string }
  | { kind: "variable"; value: "x" | "y" }
  | { kind: "identifier"; value: string }
  | { kind: "operator"; value: string }
  | { kind: "open"; value: "(" }
  | { kind: "close"; value: ")" };

function tokenizeMathSurfaceExpression(expression: string): MathSurfaceToken[] {
  const src = expression.replace(/\s+/g, "");
  const tokens: MathSurfaceToken[] = [];
  let pos = 0;
  while (pos < src.length) {
    const char = src[pos] ?? "";
    if (/[0-9.]/.test(char)) {
      const start = pos;
      pos++;
      while (/[0-9.]/.test(src[pos] ?? "")) pos++;
      if ((src[pos] ?? "").toLowerCase() === "e") {
        pos++;
        if ((src[pos] ?? "") === "+" || (src[pos] ?? "") === "-") pos++;
        while (/[0-9]/.test(src[pos] ?? "")) pos++;
      }
      tokens.push({ kind: "number", value: src.slice(start, pos) });
      continue;
    }
    if (/[A-Za-z_]/.test(char)) {
      const start = pos;
      pos++;
      while (/[A-Za-z0-9_]/.test(src[pos] ?? "")) pos++;
      const identifier = src.slice(start, pos);
      if (/^[xy]+$/i.test(identifier)) {
        for (const variable of identifier.toLowerCase()) {
          tokens.push({ kind: "variable", value: variable as "x" | "y" });
        }
      } else {
        tokens.push({ kind: "identifier", value: identifier.toLowerCase() });
      }
      continue;
    }
    if (char === "(") {
      tokens.push({ kind: "open", value: "(" });
      pos++;
      continue;
    }
    if (char === ")") {
      tokens.push({ kind: "close", value: ")" });
      pos++;
      continue;
    }
    tokens.push({ kind: "operator", value: char });
    pos++;
  }
  return tokens;
}

function insertMathSurfaceImplicitMultiplication(expression: string): string {
  const tokens = tokenizeMathSurfaceExpression(expression);
  const parts: string[] = [];
  let previous: MathSurfaceToken | null = null;
  const canEndFactor = (token: MathSurfaceToken | null) =>
    token?.kind === "number" ||
    token?.kind === "variable" ||
    token?.kind === "close";
  const canStartFactor = (token: MathSurfaceToken) =>
    token.kind === "number" ||
    token.kind === "variable" ||
    token.kind === "identifier" ||
    token.kind === "open";
  for (const token of tokens) {
    if (previous && canEndFactor(previous) && canStartFactor(token)) {
      parts.push("*");
    }
    parts.push(token.value);
    previous = token;
  }
  return parts.join("");
}

function extractMathSurfaceExpression(prompt: string): string | null {
  const compact = String(prompt ?? "")
    .replace(/\s+/g, " ")
    .trim();
  const zMatch = compact.match(
    /\bz\s*=\s*([^,;:\n]+?)(?=\s+(?:fonksiyon\w*|function|için|icin|grafi\w*|çiz|ciz|plot|surface|3d|3 boyutlu|4d|4 boyutlu)\b|$)/i,
  );
  if (zMatch?.[1]) {
    return normalizeMathSurfaceExpression(zMatch[1]);
  }
  const functionMatch = compact.match(
    /\bf\s*\(\s*x\s*,\s*y\s*\)\s*=\s*([^,;:\n]+?)(?=\s+(?:fonksiyon\w*|function|için|icin|grafi\w*|çiz|ciz|plot|surface|3d|3 boyutlu|4d|4 boyutlu)\b|$)/i,
  );
  if (functionMatch?.[1]) {
    return normalizeMathSurfaceExpression(functionMatch[1]);
  }
  return null;
}

function assertSafeMathSurfaceExpression(expression: string): void {
  const normalized = normalizeMathSurfaceExpression(expression);
  if (!normalized || normalized.length > 240) {
    throw new Error("empty_expression");
  }
  if (!/^[0-9xy+\-*/^().,\sA-Za-z]+$/.test(normalized)) {
    throw new Error("unsupported_character");
  }
  for (const match of normalized.matchAll(/[A-Za-z_][A-Za-z0-9_]*/g)) {
    if (!mathSurfaceAllowedIdentifierSet.has(match[0].toLowerCase())) {
      throw new Error("unsupported_identifier");
    }
  }
  new MathSurfaceExpressionParser(normalized).parse();
}

class MathSurfaceExpressionParser {
  private pos = 0;
  private readonly src: string;

  constructor(expression: string) {
    this.src = expression.replace(/\s+/g, "");
  }

  parse(): void {
    this.parseExpression();
    if (this.pos !== this.src.length) {
      throw new Error("unexpected_expression_tail");
    }
  }

  private parseExpression(): void {
    this.parseTerm();
    while (this.peek("+") || this.peek("-")) {
      this.pos++;
      this.parseTerm();
    }
  }

  private parseTerm(): void {
    this.parsePower();
    while (this.peek("*") || this.peek("/")) {
      this.pos++;
      this.parsePower();
    }
  }

  private parsePower(): void {
    this.parseUnary();
    if (this.peek("^")) {
      this.pos++;
      this.parsePower();
    }
  }

  private parseUnary(): void {
    if (this.peek("+") || this.peek("-")) {
      this.pos++;
      this.parseUnary();
      return;
    }
    this.parsePrimary();
  }

  private parsePrimary(): void {
    if (this.peek("(")) {
      this.pos++;
      this.parseExpression();
      this.expect(")");
      return;
    }
    const identifier = this.readIdentifier();
    if (identifier) {
      const normalized = identifier.toLowerCase();
      if (normalized === "x" || normalized === "y") {
        return;
      }
      if (!mathSurfaceAllowedIdentifierSet.has(normalized)) {
        throw new Error("unsupported_identifier");
      }
      this.expect("(");
      this.parseExpression();
      this.expect(")");
      return;
    }
    this.readNumber();
  }

  private readIdentifier(): string | null {
    const start = this.pos;
    if (!/[A-Za-z_]/.test(this.src[this.pos] ?? "")) {
      return null;
    }
    this.pos++;
    while (/[A-Za-z0-9_]/.test(this.src[this.pos] ?? "")) {
      this.pos++;
    }
    return this.src.slice(start, this.pos);
  }

  private readNumber(): void {
    const start = this.pos;
    while (/[0-9.]/.test(this.src[this.pos] ?? "")) {
      this.pos++;
    }
    if ((this.src[this.pos] ?? "").toLowerCase() === "e") {
      this.pos++;
      if (this.peek("+") || this.peek("-")) {
        this.pos++;
      }
      while (/[0-9]/.test(this.src[this.pos] ?? "")) {
        this.pos++;
      }
    }
    if (
      start === this.pos ||
      Number.isNaN(Number(this.src.slice(start, this.pos)))
    ) {
      throw new Error("expected_number");
    }
  }

  private peek(value: string): boolean {
    return this.src[this.pos] === value;
  }

  private expect(value: string): void {
    if (!this.peek(value)) {
      throw new Error("missing_token");
    }
    this.pos++;
  }
}

function buildMathSurfaceCacheKey(input: {
  expression?: string;
  range?: { x: [number, number]; y: [number, number] };
  resolution?: number;
  colorBy?: string;
}): string {
  return createHash("sha256")
    .update(JSON.stringify(input))
    .digest("hex")
    .slice(0, 24);
}

function withMathSurfaceBlockMeta(
  block: Omit<
    MathSurface3DBlock,
    "visibility" | "stableBlockId" | "cacheDigest"
  >,
): MathSurface3DBlock {
  const cacheDigest = buildMathSurfaceCacheKey({
    expression: block.expression,
    range: block.range,
    resolution: block.resolution,
    colorBy: block.colorBy,
  });
  return {
    ...block,
    visibility: "user_visible",
    stableBlockId: `math_surface_3d_${cacheDigest}`,
    cacheDigest,
  };
}

export function buildMathSurface3DResult(
  input: SharedBrainInferenceInput,
  workload: SharedBrainWorkload,
): SharedBrainInferenceResult | null {
  if (!isExplicitMathSurface3DRequest(input.prompt)) {
    return null;
  }
  const expression =
    extractMathSurfaceExpression(input.prompt) ??
    defaultMathSurfacePolynomialExpression;
  const isFourDimensional =
    /\b(4d|4 boyutlu|dört boyutlu|dort boyutlu)\b/i.test(input.prompt);
  let block: MathSurface3DBlock;
  try {
    assertSafeMathSurfaceExpression(expression);
    const range: { x: [number, number]; y: [number, number] } = {
      x: [-2, 2],
      y: [-2, 2],
    };
    const resolution = 80;
    const colorBy = isFourDimensional ? "gradientMagnitude" : "z";
    const cacheKey = buildMathSurfaceCacheKey({
      expression,
      range,
      resolution,
      colorBy,
    });
    block = withMathSurfaceBlockMeta({
      type: "math_surface_3d",
      title: `z = ${expression}`,
      expression,
      variables: ["x", "y"],
      range,
      resolution,
      zLabel: `z = ${expression}`,
      colorBy,
      mode: "surface",
      interactive: true,
      renderer: "plotly_local_webview",
      cacheKey,
      caption:
        colorBy === "gradientMagnitude"
          ? "4. boyut renk kanalında gradyan büyüklüğüyle gösterilir."
          : "Yüzey mobil cihazda yerel olarak hesaplanır ve döndürülebilir.",
    });
  } catch {
    block = withMathSurfaceBlockMeta({
      type: "math_surface_3d",
      title: "3B yüzey grafiği",
      expression,
      error: {
        code: "invalid_expression",
        message:
          "Bu ifade güvenli yüzey grafiği parser'ı tarafından desteklenmiyor.",
      },
    });
  }
  return {
    text: "",
    provider: "elyan",
    model: "deterministic-math-surface",
    latencyMs: 0,
    promptTokens: 0,
    completionTokens: 0,
    totalTokens: 0,
    metadata: {
      route: input.route ?? "shared_brain",
      workload,
      provider: "elyan",
      model: "deterministic-math-surface",
      deterministic: true,
      fallbackUsed: false,
      renderContract: {
        version: "elyan_blocks.v2",
        mode: "block_first",
        canonicalSurface: "blocks",
        legacyContent: "fallback_only",
        hasVisibleBlocks: true,
        visibleBlockTypes: ["math_surface_3d"],
        textIsBlockWrapped: false,
      },
      blocks: [block],
    },
  };
}
