/**
 * Sunucu tarafı fonksiyon/yüzey örnekleyici.
 *
 * `chartType:"function"` (2B) ve `surface3d`/`mesh`/`math_surface_3d` (3B)
 * blokları modelden `expression` + `range` ile gelir; örneklemenin İSTEMCİDE
 * yapılması varsayılıyordu ama her istemci bunu yapamıyor (native mobil
 * eskiden fonksiyon grafiğini düşürüyordu). Burada ifadeyi shunting-yard ile
 * RPN'e çevirip aralık üzerinde örnekleyerek gerçek sayısal seriye
 * dönüştürüyoruz — böylece grafik her istemcide çizilebilir ve modelin yalnız
 * ifade + aralık üretmesi yeterli oluyor.
 *
 * Kapsam: polinomlar, + − × ÷ ^, parantez, tek argümanlı beyaz-listeli
 * fonksiyonlar (sin/cos/tan/sqrt/abs/exp/ln/log/log10/sinh/cosh/tanh/asin/
 * acos/atan/sign/floor/ceil/round) ve `pi`/`e` sabitleri; değişkenler `x` ve
 * (yüzeylerde) `y`.
 *
 * GÜVENLİK: model çıktısı ASLA `eval`/`Function` ile çalıştırılmaz; yalnız
 * beyaz-listeli token'lardan oluşan güvenli bir değerlendirici kullanılır.
 * Tanınmayan bir tanımlayıcı (örn. `process`, `require`) ayrıştırmayı
 * BAŞARISIZ yapar; sessizce yok sayılmaz. Ayrıştırılamayan ifade `null` döner
 * (çağıran örnekleme yapmaz).
 */

type Token =
  | { kind: "num"; value: number }
  | { kind: "var"; name: string }
  | { kind: "func"; name: string }
  | { kind: "op"; op: string }
  | { kind: "lp" }
  | { kind: "rp" }
  | { kind: "comma" };

/** Tek argümanlı, saf (yan etkisiz) matematik fonksiyonları. */
const UNARY_FUNCTIONS: Record<string, (value: number) => number> = {
  sin: Math.sin,
  cos: Math.cos,
  tan: Math.tan,
  asin: Math.asin,
  acos: Math.acos,
  atan: Math.atan,
  sinh: Math.sinh,
  cosh: Math.cosh,
  tanh: Math.tanh,
  sqrt: Math.sqrt,
  abs: Math.abs,
  exp: Math.exp,
  ln: Math.log,
  log: Math.log,
  log10: Math.log10,
  log2: Math.log2,
  sign: Math.sign,
  floor: Math.floor,
  ceil: Math.ceil,
  round: Math.round,
};

/**
 * İki argümanlı fonksiyonlar. `pow(x,2)` model çıktısında `x^2` kadar sık
 * geçiyor; desteklenmediğinde ifade derlenmiyor ve grafik hiç çizilmiyordu.
 */
const BINARY_FUNCTIONS: Record<string, (left: number, right: number) => number> = {
  pow: Math.pow,
  atan2: Math.atan2,
  min: Math.min,
  max: Math.max,
  mod: (left, right) => (right === 0 ? NaN : left % right),
  hypot: Math.hypot,
};

function functionArity(name: string): 1 | 2 | null {
  if (name in BINARY_FUNCTIONS) return 2;
  if (name in UNARY_FUNCTIONS) return 1;
  return null;
}

const CONSTANTS: Record<string, number> = {
  pi: Math.PI,
  "π": Math.PI,
  e: Math.E,
  tau: Math.PI * 2,
};

/** Ayrıştırılmış, tekrar tekrar değerlendirilebilir ifade. */
export type CompiledExpression = {
  /** İfadede gerçekten geçen değişkenler (bildirilen sırayla). */
  variables: string[];
  evaluate: (scope: Record<string, number>) => number | null;
};

/**
 * Yazım varyantlarını tek biçime indirger. `f(x)=`, `y =`, `z=` gibi önekler
 * atılır; `²`/`³` üsse, `·`/`×` çarpıma çevrilir.
 */
function normalize(input: string): string {
  let value = String(input ?? "").trim();
  // "f(x) = x^2", "y = ...", "z = ..." → sağ taraf. Sadece sol taraf kısa bir
  // tanım başlığıysa kırpıyoruz; bu bir denklem çözücü değil.
  const equals = value.indexOf("=");
  if (equals >= 0) {
    const left = value.slice(0, equals).trim().toLowerCase();
    if (/^(f\s*\(\s*[a-z](\s*,\s*[a-z])?\s*\)|[a-z])$/.test(left)) {
      value = value.slice(equals + 1);
    }
  }
  return value
    .toLowerCase()
    .replace(/²/g, "^2")
    .replace(/³/g, "^3")
    .replace(/[·×∙]/g, "*")
    .replace(/[–—−]/g, "-")
    .replace(/÷/g, "/")
    .replace(/\s+/g, "")
    .trim();
}

function tokenize(source: string, variables: readonly string[]): Token[] | null {
  const tokens: Token[] = [];
  let index = 0;
  while (index < source.length) {
    const char = source[index];
    if (/[0-9.]/.test(char)) {
      let literal = "";
      while (index < source.length && /[0-9.]/.test(source[index])) {
        literal += source[index];
        index += 1;
      }
      // Bilimsel gösterim: `1e3`, `2.5e-4`. `e` sabitiyle karışmasın diye
      // yalnız ardından işaretli/işaretsiz rakam geliyorsa üstel sayılır.
      const afterE = source[index + 1] ?? "";
      const afterSign = source[index + 2] ?? "";
      if (
        source[index] === "e" &&
        (/[0-9]/.test(afterE) || (/[+-]/.test(afterE) && /[0-9]/.test(afterSign)))
      ) {
        literal += source[index];
        index += 1;
        if (source[index] === "+" || source[index] === "-") {
          literal += source[index];
          index += 1;
        }
        while (index < source.length && /[0-9]/.test(source[index])) {
          literal += source[index];
          index += 1;
        }
      }
      const value = Number(literal);
      if (!Number.isFinite(value)) return null;
      tokens.push({ kind: "num", value });
      continue;
    }
    if (/[a-zπ_]/.test(char)) {
      let identifier = "";
      while (index < source.length && /[a-z0-9π_]/.test(source[index])) {
        identifier += source[index];
        index += 1;
      }
      if (source[index] === "(" && functionArity(identifier) != null) {
        tokens.push({ kind: "func", name: identifier });
        continue;
      }
      if (variables.includes(identifier)) {
        tokens.push({ kind: "var", name: identifier });
        continue;
      }
      if (identifier in CONSTANTS) {
        tokens.push({ kind: "num", value: CONSTANTS[identifier] });
        continue;
      }
      // Beyaz listede olmayan her tanımlayıcı ayrıştırmayı düşürür — sessiz
      // "0 kabul et" davranışı grafiği sessizce yanlış çizerdi.
      return null;
    }
    if (char === "(") tokens.push({ kind: "lp" });
    else if (char === ")") tokens.push({ kind: "rp" });
    else if (char === ",") tokens.push({ kind: "comma" });
    else if (char === "+" || char === "-" || char === "*" || char === "/" || char === "^") {
      tokens.push({ kind: "op", op: char });
    } else return null;
    index += 1;
  }
  return tokens.length > 0 ? tokens : null;
}

/**
 * `2x`, `x(…)`, `)(`, `2sin(x)` → örtük çarpma. Token düzeyinde yapılır ki
 * fonksiyon adlarının içine `*` kaçmasın (metin düzeyinde yapılırsa `sin`
 * `s*i*n` olurdu).
 */
function insertImplicitMultiplication(tokens: Token[]): Token[] {
  const output: Token[] = [];
  for (const token of tokens) {
    const previous = output[output.length - 1];
    if (previous) {
      const previousIsValue =
        previous.kind === "num" || previous.kind === "var" || previous.kind === "rp";
      const currentOpensValue =
        token.kind === "num" ||
        token.kind === "var" ||
        token.kind === "func" ||
        token.kind === "lp";
      if (previousIsValue && currentOpensValue) {
        output.push({ kind: "op", op: "*" });
      }
    }
    output.push(token);
  }
  return output;
}

function precedence(op: string): number {
  switch (op) {
    case "+":
    case "-":
      return 1;
    case "*":
    case "/":
      return 2;
    case "n": // tekli eksi: ^'den zayıf (−x^2 = −(x^2)), *'ten güçlü
      return 3;
    case "^":
      return 4;
    default:
      return 0;
  }
}

function toRpn(tokens: Token[]): Token[] | null {
  const output: Token[] = [];
  const stack: Token[] = [];
  let previous: Token | null = null;
  for (const token of tokens) {
    if (token.kind === "num" || token.kind === "var") {
      output.push(token);
    } else if (token.kind === "func") {
      stack.push(token);
    } else if (token.kind === "op") {
      const unary =
        token.op === "-" &&
        (previous === null || previous.kind === "lp" || previous.kind === "op");
      if (unary) {
        stack.push({ kind: "op", op: "n" });
      } else if (token.op === "+" && (previous === null || previous.kind === "lp")) {
        // Tekli artı: anlamsız, yok sayılır.
      } else {
        const rightAssociative = token.op === "^";
        while (stack.length > 0 && stack[stack.length - 1].kind === "op") {
          const top = stack[stack.length - 1] as { kind: "op"; op: string };
          const shouldPop = rightAssociative
            ? precedence(top.op) > precedence(token.op)
            : precedence(top.op) >= precedence(token.op);
          if (shouldPop) output.push(stack.pop() as Token);
          else break;
        }
        stack.push(token);
      }
    } else if (token.kind === "lp") {
      stack.push(token);
    } else if (token.kind === "comma") {
      // Argüman ayracı: açık parantezin üstündeki operatörler boşaltılır,
      // parantez yerinde kalır (bir sonraki argüman aynı çağrıya ait).
      while (stack.length > 0 && stack[stack.length - 1].kind !== "lp") {
        output.push(stack.pop() as Token);
      }
      if (stack.length === 0) return null;
    } else {
      while (stack.length > 0 && stack[stack.length - 1].kind !== "lp") {
        output.push(stack.pop() as Token);
      }
      if (stack.length === 0 || stack[stack.length - 1].kind !== "lp") return null;
      stack.pop();
      // Kapanan parantez bir fonksiyon çağrısını bitiriyorsa fonksiyonu yay.
      if (stack.length > 0 && stack[stack.length - 1].kind === "func") {
        output.push(stack.pop() as Token);
      }
    }
    previous = token;
  }
  while (stack.length > 0) {
    const top = stack.pop() as Token;
    if (top.kind === "lp") return null;
    output.push(top);
  }
  return output.length > 0 ? output : null;
}

function evalRpn(rpn: Token[], scope: Record<string, number>): number | null {
  const stack: number[] = [];
  for (const token of rpn) {
    if (token.kind === "num") {
      stack.push(token.value);
    } else if (token.kind === "var") {
      const value = scope[token.name];
      if (typeof value !== "number" || !Number.isFinite(value)) return null;
      stack.push(value);
    } else if (token.kind === "func") {
      const arity = functionArity(token.name);
      if (arity === 2) {
        const right = stack.pop();
        const left = stack.pop();
        if (left === undefined || right === undefined) return null;
        stack.push(BINARY_FUNCTIONS[token.name](left, right));
      } else if (arity === 1) {
        const argument = stack.pop();
        if (argument === undefined) return null;
        stack.push(UNARY_FUNCTIONS[token.name](argument));
      } else return null;
    } else if (token.kind === "op" && token.op === "n") {
      const argument = stack.pop();
      if (argument === undefined) return null;
      stack.push(-argument);
    } else if (token.kind === "op") {
      const right = stack.pop();
      const left = stack.pop();
      if (left === undefined || right === undefined) return null;
      switch (token.op) {
        case "+":
          stack.push(left + right);
          break;
        case "-":
          stack.push(left - right);
          break;
        case "*":
          stack.push(left * right);
          break;
        case "/":
          stack.push(right === 0 ? NaN : left / right);
          break;
        case "^":
          stack.push(Math.pow(left, right));
          break;
        default:
          return null;
      }
    } else return null;
  }
  return stack.length === 1 ? stack[0] : null;
}

/**
 * İfadeyi bir kez ayrıştırır; ızgara örneklemede binlerce kez yeniden
 * ayrıştırmamak için değerlendirici döner. Ayrıştırılamazsa `null`.
 */
export function compileExpression(
  expression: string,
  variables: readonly string[] = ["x"],
): CompiledExpression | null {
  const source = normalize(expression);
  if (!source) return null;
  const tokens = tokenize(source, variables);
  if (!tokens) return null;
  const rpn = toRpn(insertImplicitMultiplication(tokens));
  if (!rpn) return null;
  const used = variables.filter((name) =>
    rpn.some((token) => token.kind === "var" && token.name === name),
  );
  return {
    variables: used,
    evaluate: (scope) => {
      const value = evalRpn(rpn, scope);
      return value != null && Number.isFinite(value) ? value : null;
    },
  };
}

type Bounds = { min: number; max: number };

function readAxis(value: unknown): Bounds | null {
  if (Array.isArray(value) && value.length >= 2) {
    const min = Number(value[0]);
    const max = Number(value[1]);
    if (Number.isFinite(min) && Number.isFinite(max) && min < max) {
      return { min, max };
    }
    return null;
  }
  if (value && typeof value === "object") {
    const record = value as Record<string, unknown>;
    const min = Number(record.min ?? record.from ?? record.start);
    const max = Number(record.max ?? record.to ?? record.end);
    if (Number.isFinite(min) && Number.isFinite(max) && min < max) {
      return { min, max };
    }
  }
  return null;
}

/** `range` gövdesinden bir eksenin sınırlarını çıkarır; yoksa varsayılan. */
export function resolveRangeAxis(
  range: unknown,
  axis: "x" | "y",
  fallback: Bounds = { min: -10, max: 10 },
): Bounds {
  if (Array.isArray(range)) {
    return readAxis(range) ?? fallback;
  }
  const record =
    range && typeof range === "object" ? (range as Record<string, unknown>) : null;
  if (!record) return fallback;
  const direct = readAxis(record[axis] ?? record[axis.toUpperCase()]);
  if (direct) return direct;
  const flat = readAxis({
    min: record[`${axis}Min`] ?? record[`${axis}min`],
    max: record[`${axis}Max`] ?? record[`${axis}max`],
  });
  return flat ?? fallback;
}

function formatLabel(value: number): string {
  const rounded = Math.round(value);
  if (Math.abs(rounded - value) < 1e-9) return String(rounded);
  return Number(value.toFixed(4)).toString();
}

/**
 * Tek değişkenli (x) bir ifadeyi aralık üzerinde örnekler. Başarısızsa `null`.
 *
 * Süreksizlikte (1/x, tan x, √negatif) o örnek ATLANIR — tüm seri düşmez.
 */
export function sampleFunctionChart(
  expression: string,
  range: unknown,
  samples = 96,
): { labels: string[]; values: number[]; points: Array<{ x: number; y: number }> } | null {
  const compiled = compileExpression(expression, ["x"]);
  if (!compiled) return null;
  const { min, max } = resolveRangeAxis(range, "x");
  const count = Math.max(2, Math.min(240, Math.trunc(samples)));
  const step = (max - min) / (count - 1);
  const labels: string[] = [];
  const values: number[] = [];
  const points: Array<{ x: number; y: number }> = [];
  for (let index = 0; index < count; index += 1) {
    const x = min + index * step;
    const y = compiled.evaluate({ x });
    if (y == null) continue;
    labels.push(formatLabel(x));
    values.push(Number(y.toFixed(6)));
    points.push({ x: Number(x.toFixed(6)), y: Number(y.toFixed(6)) });
  }
  return values.length >= 2 ? { labels, values, points } : null;
}

/**
 * İki değişkenli (x, y) bir ifadeyi ızgara üzerinde örnekler — `surface3d`,
 * `mesh` ve `math_surface_3d` blokları için. Nokta sayısı `resolution²`
 * olduğundan çözünürlük sıkı sınırlanır (varsayılan 32×32 = 1024 nokta,
 * blok şemasının 1.500 nokta sınırının altında).
 */
export function sampleSurfaceGrid(
  expression: string,
  range: unknown,
  resolution = 32,
): {
  points: Array<{ x: number; y: number; z: number }>;
  resolution: number;
  xRange: [number, number];
  yRange: [number, number];
  zRange: [number, number];
} | null {
  const compiled = compileExpression(expression, ["x", "y"]);
  if (!compiled) return null;
  const size = Math.max(8, Math.min(38, Math.trunc(resolution)));
  const xBounds = resolveRangeAxis(range, "x", { min: -5, max: 5 });
  const yBounds = resolveRangeAxis(range, "y", { min: -5, max: 5 });
  const xStep = (xBounds.max - xBounds.min) / (size - 1);
  const yStep = (yBounds.max - yBounds.min) / (size - 1);
  const points: Array<{ x: number; y: number; z: number }> = [];
  let zMin = Number.POSITIVE_INFINITY;
  let zMax = Number.NEGATIVE_INFINITY;
  for (let row = 0; row < size; row += 1) {
    const y = yBounds.min + row * yStep;
    for (let column = 0; column < size; column += 1) {
      const x = xBounds.min + column * xStep;
      const z = compiled.evaluate({ x, y });
      if (z == null) continue;
      points.push({
        x: Number(x.toFixed(4)),
        y: Number(y.toFixed(4)),
        z: Number(z.toFixed(4)),
      });
      if (z < zMin) zMin = z;
      if (z > zMax) zMax = z;
    }
  }
  if (points.length < 16) return null;
  return {
    points,
    resolution: size,
    xRange: [xBounds.min, xBounds.max],
    yRange: [yBounds.min, yBounds.max],
    zRange: [zMin, zMax],
  };
}

/** İfade sunucuda örneklenebilir mi? (Tek/iki değişkenli, beyaz-listeli.) */
export function isSampleableExpression(
  expression: string,
  variables: readonly string[] = ["x"],
): boolean {
  return compileExpression(expression, variables) != null;
}
