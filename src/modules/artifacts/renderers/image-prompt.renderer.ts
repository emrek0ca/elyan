import type { ArtifactOutput, ArtifactRenderer, ImagePromptSpec, ValidationResult } from "../types.js";
import { validateImagePromptSpec } from "../validators/image-prompt.validator.js";

export class ImagePromptRenderer implements ArtifactRenderer<ImagePromptSpec> {
  supports(type: string): boolean {
    return type === "image_prompt";
  }

  async validate(spec: ImagePromptSpec): Promise<ValidationResult> {
    return validateImagePromptSpec(spec);
  }

  async render(spec: ImagePromptSpec): Promise<ArtifactOutput> {
    const validation = await this.validate(spec);
    const constraintText = spec.constraints.length > 0
      ? `\n\nConstraints:\n${spec.constraints.map((item) => `- ${item}`).join("\n")}`
      : "";
    const negativeText = spec.negativePrompt?.length
      ? `\n\nNegative prompt:\n${spec.negativePrompt.join(", ")}`
      : "";
    return {
      artifactId: spec.id,
      type: "image_prompt",
      spec,
      output: {
        kind: "text",
        content: `${spec.prompt}${constraintText}${negativeText}`.trim(),
      },
      validation,
    };
  }
}
