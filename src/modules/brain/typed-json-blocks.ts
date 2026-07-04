// LLM'ler document_block JSON'unu üretirken string DEĞERLERİNİN içine sık sık
// literal satır başı/tab koyar. Bu GEÇERSİZ JSON'dur ve JSON.parse patlar.
function repairLooseJsonObject(candidate: string): string {
  let out = "";
  let inString = false;
  let escaped = false;
  for (let i = 0; i < candidate.length; i++) {
    const ch = candidate[i];
    if (escaped) {
      out += ch;
      escaped = false;
      continue;
    }
    if (ch === "\\") {
      out += ch;
      escaped = true;
      continue;
    }
    if (ch === '"') {
      inString = !inString;
      out += ch;
      continue;
    }
    if (inString) {
      if (ch === "\n") {
        out += "\\n";
        continue;
      }
      if (ch === "\r") {
        out += "\\r";
        continue;
      }
      if (ch === "\t") {
        out += "\\t";
        continue;
      }
    }
    out += ch;
  }
  return out;
}

function coerceMalformedTypedBlock(
  candidate: string,
): Record<string, unknown> | null {
  const typeMatch = candidate.match(/"type"\s*:\s*"([a-z0-9_]+)"/i);
  if (!typeMatch) {
    return null;
  }
  const type = typeMatch[1].toLowerCase();

  const pickString = (key: string): string | undefined => {
    const match = candidate.match(
      new RegExp(`"${key}"\\s*:\\s*"((?:[^"\\\\]|\\\\.)*)"`, "i"),
    );
    return match ? match[1] : undefined;
  };
  const pickBool = (key: string): boolean | undefined => {
    const match = candidate.match(
      new RegExp(`"${key}"\\s*:\\s*(true|false)`, "i"),
    );
    return match ? match[1].toLowerCase() === "true" : undefined;
  };

  const block: Record<string, unknown> = { type };
  const assignString = (key: string): void => {
    const value = pickString(key);
    if (value !== undefined) {
      block[key] = value;
    }
  };
  for (const key of [
    "title",
    "content",
    "format",
    "result",
    "expression",
    "language",
    "code",
    "caption",
    "summary",
  ]) {
    assignString(key);
  }
  const displayMode = pickBool("displayMode");
  if (displayMode !== undefined) {
    block.displayMode = displayMode;
  }

  const hasPayload =
    typeof block.content === "string" ||
    typeof block.expression === "string" ||
    typeof block.code === "string" ||
    typeof block.result === "string";
  return hasPayload ? block : null;
}

function tryParseTypedJsonObject(
  candidate: string,
): Record<string, unknown> | null {
  for (const variant of [candidate, repairLooseJsonObject(candidate)]) {
    try {
      const parsed = JSON.parse(variant);
      if (
        parsed &&
        typeof parsed === "object" &&
        !Array.isArray(parsed) &&
        typeof (parsed as Record<string, unknown>).type === "string"
      ) {
        return parsed as Record<string, unknown>;
      }
    } catch {
      /* try next variant */
    }
  }
  return coerceMalformedTypedBlock(candidate);
}

function findBalancedObjectEnd(text: string, braceIdx: number): number {
  let depth = 0;
  let inString = false;
  let escaped = false;
  for (let j = braceIdx; j < text.length; j++) {
    const ch = text[j];
    if (escaped) {
      escaped = false;
      continue;
    }
    if (ch === "\\") {
      escaped = true;
      continue;
    }
    if (ch === '"') {
      inString = !inString;
      continue;
    }
    if (inString) {
      continue;
    }
    if (ch === "{") {
      depth++;
    } else if (ch === "}") {
      depth--;
      if (depth === 0) {
        return j;
      }
    }
  }
  return -1;
}

function unwrapPlainBraceSentence(candidate: string): string {
  const inner = candidate.slice(1, -1).trim();
  const quoted = inner.match(/^"((?:[^"\\]|\\.)*)"$/);
  if (quoted) {
    return quoted[1];
  }
  return "";
}

export function extractTypedJsonBlocksFromText(text: string): {
  visibleText: string;
  blocks: unknown[];
} {
  const blocks: unknown[] = [];
  const seen = new Set<string>();

  const fencePattern = /```(?:json)?\s*([\s\S]*?)```/g;
  let visibleText = text;
  let match: RegExpExecArray | null;

  while ((match = fencePattern.exec(text)) !== null) {
    const candidate = match[1].trim();
    if (!candidate.startsWith("{")) continue;
    const parsed = tryParseTypedJsonObject(candidate);
    if (parsed) {
      const dedupKey = JSON.stringify(parsed);
      if (!seen.has(dedupKey)) {
        seen.add(dedupKey);
        blocks.push(parsed);
      }
      visibleText = visibleText.replace(match[0], "").trim();
    }
  }

  if (blocks.length === 0) {
    let working = visibleText;
    let guard = 0;
    while (guard++ < 8) {
      const braceIdx = working.indexOf("{");
      if (braceIdx < 0) {
        break;
      }
      const end = findBalancedObjectEnd(working, braceIdx);
      if (end < 0) {
        break;
      }
      const candidate = working.slice(braceIdx, end + 1);
      const parsed = tryParseTypedJsonObject(candidate);
      if (parsed) {
        const dedupKey = JSON.stringify(parsed);
        if (!seen.has(dedupKey)) {
          seen.add(dedupKey);
          blocks.push(parsed);
        }
        working = (working.slice(0, braceIdx) + working.slice(end + 1)).trim();
      } else {
        const unwrapped = unwrapPlainBraceSentence(candidate);
        working = (
          working.slice(0, braceIdx) +
          unwrapped +
          working.slice(end + 1)
        ).trim();
      }
    }
    visibleText = working;
  }

  if (blocks.length === 0) {
    const braceIdx = visibleText.indexOf("{");
    if (braceIdx >= 0) {
      const region = visibleText.slice(braceIdx);
      if (/"type"\s*:/.test(region)) {
        const coerced = coerceMalformedTypedBlock(region);
        if (coerced) {
          blocks.push(coerced);
          visibleText = visibleText.slice(0, braceIdx).trim();
        }
      }
    }
  }

  return { visibleText, blocks };
}

export function computeStreamVisibleText(full: string): string {
  let visible = full;

  const fencePattern = /```(?:json)?\s*([\s\S]*?)```/g;
  let fenceMatch: RegExpExecArray | null;
  const fencesToStrip: string[] = [];
  while ((fenceMatch = fencePattern.exec(full)) !== null) {
    const inner = fenceMatch[1].trim();
    if (inner.startsWith("{") && tryParseTypedJsonObject(inner)) {
      fencesToStrip.push(fenceMatch[0]);
    }
  }
  for (const fence of fencesToStrip) {
    visible = visible.replace(fence, "");
  }

  const fenceCount = (visible.match(/```/g) ?? []).length;
  if (fenceCount % 2 === 1) {
    const openFenceIdx = visible.lastIndexOf("```");
    if (openFenceIdx >= 0) {
      visible = visible.slice(0, openFenceIdx).trimEnd();
    }
  }

  let working = visible;
  let out = "";
  let guard = 0;
  while (guard++ < 16) {
    const braceIdx = working.indexOf("{");
    if (braceIdx < 0) {
      out += working;
      break;
    }
    const end = findBalancedObjectEnd(working, braceIdx);
    if (end < 0) {
      out += working.slice(0, braceIdx);
      working = "";
      break;
    }
    const candidate = working.slice(braceIdx, end + 1);
    out += working.slice(0, braceIdx);
    if (!tryParseTypedJsonObject(candidate)) {
      out += unwrapPlainBraceSentence(candidate) || candidate;
    }
    working = working.slice(end + 1);
  }

  return out.trim();
}
