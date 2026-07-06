import type { ArtifactOutput, ArtifactRenderer, ChartSpec, ValidationResult } from "../types.js";
import { validateChartSpec } from "../validators/chart.validator.js";

export class ChartRenderer implements ArtifactRenderer<ChartSpec> {
  supports(type: string): boolean {
    return type === "chart";
  }

  async validate(spec: ChartSpec): Promise<ValidationResult> {
    return validateChartSpec(spec);
  }

  async render(spec: ChartSpec): Promise<ArtifactOutput> {
    const validation = await this.validate(spec);
    return {
      artifactId: spec.id,
      type: "chart",
      spec,
      output: {
        kind: "json",
        content: {
          chartType: spec.chartType,
          xKey: spec.xKey ?? "label",
          yKey: spec.yKey ?? "value",
          series: spec.series ?? [],
          data: spec.data,
        },
      },
      validation,
    };
  }
}
