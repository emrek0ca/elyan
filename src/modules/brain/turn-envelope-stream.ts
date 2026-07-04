type ReplyTextScanResult = {
  text: string;
  found: boolean;
  complete: boolean;
  failed: boolean;
};

function skipWhitespace(input: string, index: number): number {
  let cursor = index;
  while (cursor < input.length && /\s/.test(input[cursor] ?? "")) {
    cursor += 1;
  }
  return cursor;
}

function decodeJsonStringPrefix(input: string, quoteIndex: number): {
  value: string;
  complete: boolean;
  failed: boolean;
} {
  if (input[quoteIndex] !== "\"") {
    return { value: "", complete: false, failed: true };
  }

  let cursor = quoteIndex + 1;
  let value = "";
  while (cursor < input.length) {
    const char = input[cursor] ?? "";
    if (char === "\"") {
      return { value, complete: true, failed: false };
    }
    if (char !== "\\") {
      value += char;
      cursor += 1;
      continue;
    }

    if (cursor + 1 >= input.length) {
      return { value, complete: false, failed: false };
    }
    const escaped = input[cursor + 1] ?? "";
    if (escaped === "\"" || escaped === "\\" || escaped === "/") {
      value += escaped;
      cursor += 2;
      continue;
    }
    if (escaped === "b") {
      value += "\b";
      cursor += 2;
      continue;
    }
    if (escaped === "f") {
      value += "\f";
      cursor += 2;
      continue;
    }
    if (escaped === "n") {
      value += "\n";
      cursor += 2;
      continue;
    }
    if (escaped === "r") {
      value += "\r";
      cursor += 2;
      continue;
    }
    if (escaped === "t") {
      value += "\t";
      cursor += 2;
      continue;
    }
    if (escaped === "u") {
      const hex = input.slice(cursor + 2, cursor + 6);
      if (hex.length < 4) {
        return { value, complete: false, failed: false };
      }
      if (!/^[0-9a-fA-F]{4}$/.test(hex)) {
        return { value, complete: false, failed: true };
      }
      value += String.fromCharCode(Number.parseInt(hex, 16));
      cursor += 6;
      continue;
    }
    return { value, complete: false, failed: true };
  }

  return { value, complete: false, failed: false };
}

function findPropertyValueQuote(input: string, property: string, fromIndex = 0): number {
  const pattern = `"${property}"`;
  let cursor = input.indexOf(pattern, fromIndex);
  while (cursor >= 0) {
    let afterKey = skipWhitespace(input, cursor + pattern.length);
    if (input[afterKey] !== ":") {
      cursor = input.indexOf(pattern, cursor + pattern.length);
      continue;
    }
    afterKey = skipWhitespace(input, afterKey + 1);
    return input[afterKey] === "\"" ? afterKey : -1;
  }
  return -1;
}

function scanReplyText(input: string): ReplyTextScanResult {
  const replyKey = input.indexOf("\"reply\"");
  if (replyKey < 0) {
    return { text: "", found: false, complete: false, failed: false };
  }
  const replyObjectStart = input.indexOf("{", replyKey);
  if (replyObjectStart < 0) {
    return { text: "", found: true, complete: false, failed: false };
  }
  const textQuote = findPropertyValueQuote(input, "text", replyObjectStart);
  if (textQuote < 0) {
    return { text: "", found: true, complete: false, failed: false };
  }
  const decoded = decodeJsonStringPrefix(input, textQuote);
  return {
    text: decoded.value,
    found: true,
    complete: decoded.complete,
    failed: decoded.failed,
  };
}

export type TurnEnvelopeReplyTextStreamParser = {
  push(chunk: string): { delta: string; content: string; failed: boolean };
  finish(): { text: string; failed: boolean };
};

export function createTurnEnvelopeReplyTextStreamParser(): TurnEnvelopeReplyTextStreamParser {
  let buffer = "";
  let lastText = "";
  let failed = false;

  return {
    push(chunk: string) {
      if (failed) {
        return { delta: "", content: lastText, failed };
      }
      buffer += chunk;
      const scanned = scanReplyText(buffer);
      if (scanned.failed) {
        failed = true;
        return { delta: "", content: lastText, failed };
      }
      if (!scanned.found) {
        return { delta: "", content: lastText, failed };
      }
      if (!scanned.text.startsWith(lastText)) {
        failed = true;
        return { delta: "", content: lastText, failed };
      }
      const delta = scanned.text.slice(lastText.length);
      lastText = scanned.text;
      return { delta, content: lastText, failed };
    },
    finish() {
      return { text: lastText, failed };
    },
  };
}
