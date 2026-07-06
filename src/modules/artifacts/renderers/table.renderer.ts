import type { ArtifactOutput, ArtifactRenderer, TableSpec, ValidationResult } from "../types.js";
import { validateTableSpec } from "../validators/table.validator.js";

export class TableRenderer implements ArtifactRenderer<TableSpec> {
  supports(type: string): boolean {
    return type === "table";
  }

  async validate(spec: TableSpec): Promise<ValidationResult> {
    return validateTableSpec(spec);
  }

  async render(spec: TableSpec): Promise<ArtifactOutput> {
    const validation = await this.validate(spec);
    return {
      artifactId: spec.id,
      type: "table",
      spec,
      output: {
        kind: "json",
        content: {
          columns: spec.columns,
          rows: spec.rows,
          summary: spec.summary ?? null,
        },
      },
      validation,
    };
  }
}
