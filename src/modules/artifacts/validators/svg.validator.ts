import type { SvgSpec, ValidationIssue, ValidationResult } from "../types.js";

function issue(code: string, message: string, path: string, severity: "error" | "warning" = "error"): ValidationIssue {
  return { code, message, path, severity };
}

function numberValue(value: unknown): number | null {
  return typeof value === "number" && Number.isFinite(value) ? value : null;
}

const SAFE_SVG_TAGS = new Set([
  "svg",
  "g",
  "defs",
  "lineargradient",
  "radialgradient",
  "stop",
  "clippath",
  "mask",
  "pattern",
  "rect",
  "circle",
  "ellipse",
  "line",
  "path",
  "polygon",
  "polyline",
  "text",
  "tspan",
  "title",
  "desc",
]);

export function validateSvgSpec(spec: SvgSpec): ValidationResult {
  const issues: ValidationIssue[] = [];
  if (spec.elements.length === 0 && !spec.markup?.trim()) {
    issues.push(issue("svg_content_missing", "SVG content is required.", "elements"));
  }
  if (spec.markup) {
    if (!/^\s*<svg\b[\s\S]*<\/svg>\s*$/iu.test(spec.markup)) {
      issues.push(issue("invalid_svg_markup", "SVG markup must contain one complete svg root.", "markup"));
    }
    const unsafeMarkup =
      /<\s*(?:script|style|foreignObject|iframe|object|embed|audio|video|image|a|use|animate|animateTransform|set)\b|<\s*!(?:DOCTYPE|ENTITY)\b|<\?|\son[a-z]+\s*=|\sstyle\s*=|@import|url\s*\(/iu.test(
        spec.markup,
      );
    const unsafeHref = [...spec.markup.matchAll(/(?:href|xlink:href)\s*=\s*["']([^"']*)["']/giu)]
      .some((match) => !/^#[a-z_][\w:.-]*$/iu.test(match[1]?.trim() ?? ""));
    const unsafeTag = [...spec.markup.matchAll(/<\s*\/?\s*([a-z][\w:.-]*)\b/giu)]
      .some((match) => {
        const tag = (match[1] ?? "").toLowerCase();
        return tag.includes(":") || !SAFE_SVG_TAGS.has(tag);
      });
    if (unsafeMarkup || unsafeHref || unsafeTag) {
      issues.push(issue("unsafe_svg_markup", "SVG markup contains executable or external content.", "markup"));
    }
  }
  if (!spec.canvas.viewBox.trim()) {
    issues.push(issue("missing_viewbox", "SVG viewBox is required.", "canvas.viewBox"));
  }
  if (spec.canvas.width <= 0 || spec.canvas.height <= 0) {
    issues.push(issue("invalid_canvas_size", "SVG width and height must be positive.", "canvas"));
  }

  spec.elements.forEach((element, index) => {
    const x = numberValue(element.x);
    const y = numberValue(element.y);
    const width = numberValue(element.width);
    const height = numberValue(element.height);
    const cx = numberValue(element.cx);
    const cy = numberValue(element.cy);
    const r = numberValue(element.r);
    if (x != null && (x < 0 || x > spec.canvas.width)) {
      issues.push(issue("element_out_of_bounds", "SVG element x is outside the canvas.", `elements.${index}.x`));
    }
    if (y != null && (y < 0 || y > spec.canvas.height)) {
      issues.push(issue("element_out_of_bounds", "SVG element y is outside the canvas.", `elements.${index}.y`));
    }
    if (width != null && x != null && x + width > spec.canvas.width) {
      issues.push(issue("element_out_of_bounds", "SVG element width exceeds the canvas.", `elements.${index}.width`));
    }
    if (height != null && y != null && y + height > spec.canvas.height) {
      issues.push(issue("element_out_of_bounds", "SVG element height exceeds the canvas.", `elements.${index}.height`));
    }
    if (r != null && cx != null && cy != null && (cx - r < 0 || cy - r < 0 || cx + r > spec.canvas.width || cy + r > spec.canvas.height)) {
      issues.push(issue("element_out_of_bounds", "SVG circle exceeds the canvas.", `elements.${index}`));
    }
    if (element.type === "text") {
      const fontSize = numberValue(element.fontSize);
      if (fontSize == null || fontSize < 8) {
        issues.push(issue("text_too_small", "SVG text needs a readable fontSize.", `elements.${index}.fontSize`));
      }
    }
    if (element.type === "path") {
      const path = String(element.d ?? "").trim();
      if (!/^[MmLlHhVvCcSsQqTtAaZz0-9,.\s-]+$/.test(path)) {
        issues.push(issue("invalid_path", "SVG path contains unsupported commands.", `elements.${index}.d`));
      }
      if (path.length > 4_000) {
        issues.push(issue("path_too_complex", "SVG path is unnecessarily complex.", `elements.${index}.d`, "warning"));
      }
    }
  });

  return {
    ok: issues.every((entry) => entry.severity !== "error"),
    errors: issues,
    warnings: issues
      .filter((entry) => entry.severity === "warning")
      .map(({ code, message, path }) => ({ code, message, path })),
  };
}
