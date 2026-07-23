import type { ArtifactOutput, ArtifactRenderer, SvgSpec, ValidationResult } from "../types.js";
import { validateSvgSpec } from "../validators/svg.validator.js";

function escapeXml(value: unknown): string {
  return String(value ?? "")
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;");
}

function attrs(record: Record<string, unknown>, keys: string[]): string {
  return keys
    .map((key) => record[key] == null ? "" : `${key}="${escapeXml(record[key])}"`)
    .filter(Boolean)
    .join(" ");
}

function renderElement(element: Record<string, unknown>): string {
  switch (element.type) {
    case "rect":
      return `<rect ${attrs(element, ["x", "y", "width", "height", "rx", "fill", "stroke", "strokeWidth"])} />`;
    case "circle":
      return `<circle ${attrs(element, ["cx", "cy", "r", "fill", "stroke", "strokeWidth"])} />`;
    case "line":
      return `<line ${attrs(element, ["x1", "y1", "x2", "y2", "stroke", "strokeWidth"])} />`;
    case "path":
      return `<path ${attrs(element, ["d", "fill", "stroke", "strokeWidth"])} />`;
    case "polygon":
      return `<polygon ${attrs(element, ["points", "fill", "stroke", "strokeWidth"])} />`;
    case "polyline":
      return `<polyline ${attrs(element, ["points", "fill", "stroke", "strokeWidth"])} />`;
    case "text":
      return `<text ${attrs(element, ["x", "y", "fontSize", "fontFamily", "fill", "textAnchor", "dominantBaseline"])}>${escapeXml(element.text)}</text>`;
    case "group": {
      const children = Array.isArray(element.children)
        ? element.children.map((child) => renderElement(child as Record<string, unknown>)).join("")
        : "";
      return `<g ${attrs(element, ["fill", "stroke", "transform"])}>${children}</g>`;
    }
    default:
      return "";
  }
}

export class SvgRenderer implements ArtifactRenderer<SvgSpec> {
  supports(type: string): boolean {
    return type === "svg";
  }

  async validate(spec: SvgSpec): Promise<ValidationResult> {
    return validateSvgSpec(spec);
  }

  async render(spec: SvgSpec): Promise<ArtifactOutput> {
    const validation = await this.validate(spec);
    const body = spec.elements.map((element) => renderElement(element as Record<string, unknown>)).join("\n  ");
    const svg = spec.markup?.trim() || `<svg xmlns="http://www.w3.org/2000/svg" width="${spec.canvas.width}" height="${spec.canvas.height}" viewBox="${escapeXml(spec.canvas.viewBox)}">\n  ${body}\n</svg>`;
    return {
      artifactId: spec.id,
      type: "svg",
      spec,
      output: { kind: "svg", content: svg },
      validation,
    };
  }
}
