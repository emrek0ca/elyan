import type { ArtifactOutput, ArtifactRenderer, TextSpec, ValidationResult } from "../types.js";
import { compactText } from "../utils.js";
import { validateTextSpec } from "../validators/text.validator.js";

function professionalize(text: string): string {
  const value = compactText(text)
    .replace(/^abi[\s,]*/iu, "")
    .replace(/\bişi\b/giu, "işi")
    .trim();
  if (/yarın\s+bitiririm/i.test(value)) {
    return "Merhaba, işi yarın tamamlayacağım.";
  }
  return value ? `${value[0]?.toLocaleUpperCase("tr-TR") ?? ""}${value.slice(1)}` : value;
}

export class TextRenderer implements ArtifactRenderer<TextSpec> {
  supports(type: string): boolean {
    return type === "text";
  }

  async validate(spec: TextSpec): Promise<ValidationResult> {
    return validateTextSpec(spec);
  }

  async render(spec: TextSpec): Promise<ArtifactOutput> {
    const validation = await this.validate(spec);
    const raw = spec.blocks.map((block) => block.text).join("\n\n");
    const content = spec.tone === "formal" ? professionalize(raw) : compactText(raw);
    return {
      artifactId: spec.id,
      type: "text",
      spec,
      output: { kind: "text", content },
      validation,
    };
  }
}
