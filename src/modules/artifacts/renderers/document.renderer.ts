import type { ArtifactOutput, ArtifactRenderer, DocumentSpec, ValidationResult } from "../types.js";
import { validateDocumentSpec } from "../validators/document.validator.js";

export class DocumentRenderer implements ArtifactRenderer<DocumentSpec> {
  supports(type: string): boolean {
    return type === "document";
  }

  async validate(spec: DocumentSpec): Promise<ValidationResult> {
    return validateDocumentSpec(spec);
  }

  async render(spec: DocumentSpec): Promise<ArtifactOutput> {
    const validation = await this.validate(spec);
    return {
      artifactId: spec.id,
      type: "document",
      spec,
      output: {
        kind: "json",
        content: {
          title: spec.title ?? null,
          documentType: spec.documentType,
          language: spec.language,
          sections: spec.sections,
          exportFormats: spec.exportFormats ?? ["pdf", "docx"],
        },
      },
      validation,
    };
  }
}
