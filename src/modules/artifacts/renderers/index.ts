import type { ArtifactRenderer, ArtifactSpec } from "../types.js";
import { ChartRenderer } from "./chart.renderer.js";
import { DocumentRenderer } from "./document.renderer.js";
import { ImagePromptRenderer } from "./image-prompt.renderer.js";
import { PdfRenderer } from "./pdf.renderer.js";
import { SvgRenderer } from "./svg.renderer.js";
import { TableRenderer } from "./table.renderer.js";
import { TextRenderer } from "./text.renderer.js";

const renderers: ArtifactRenderer[] = [
  new PdfRenderer(),
  new TableRenderer(),
  new ChartRenderer(),
  new SvgRenderer(),
  new TextRenderer(),
  new DocumentRenderer(),
  new ImagePromptRenderer(),
];

export function rendererForSpec(spec: ArtifactSpec): ArtifactRenderer {
  const renderer = renderers.find((candidate) => candidate.supports(spec.type));
  if (!renderer) {
    throw new Error(`No renderer registered for artifact type ${spec.type}`);
  }
  return renderer;
}
