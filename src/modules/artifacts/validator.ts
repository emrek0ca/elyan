import type { ArtifactSpec, ValidationResult } from "./types.js";
import { validateChartSpec } from "./validators/chart.validator.js";
import { validateDocumentSpec } from "./validators/document.validator.js";
import { validateImagePromptSpec } from "./validators/image-prompt.validator.js";
import { validatePdfSpec } from "./validators/pdf.validator.js";
import { validateSvgSpec } from "./validators/svg.validator.js";
import { validateTableSpec } from "./validators/table.validator.js";
import { validateTextSpec } from "./validators/text.validator.js";

export function validateArtifactSpec(spec: ArtifactSpec): ValidationResult {
  switch (spec.type) {
    case "pdf":
      return validatePdfSpec(spec);
    case "table":
      return validateTableSpec(spec);
    case "chart":
      return validateChartSpec(spec);
    case "svg":
      return validateSvgSpec(spec);
    case "text":
      return validateTextSpec(spec);
    case "document":
      return validateDocumentSpec(spec);
    case "image_prompt":
      return validateImagePromptSpec(spec);
  }
}
