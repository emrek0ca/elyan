import { artifactSpecSchema, type ArtifactSpec } from "./types.js";
import { formatMoney, normalizeKey } from "./utils.js";

export function normalizeArtifactSpec(spec: ArtifactSpec): ArtifactSpec {
  const normalized = (() => {
    switch (spec.type) {
      case "table":
        return {
          ...spec,
          columns: spec.columns.map((column) => ({
            ...column,
            key: normalizeKey(column.key || column.label),
          })),
          rows: spec.rows.map((row) => {
            const next: Record<string, unknown> = {};
            for (const column of spec.columns) {
              const key = normalizeKey(column.key || column.label);
              const value = row[column.key] ?? row[key] ?? row[column.label];
              next[key] = value;
            }
            return next;
          }),
        };
      case "chart":
        return {
          ...spec,
          xKey: spec.xKey ? normalizeKey(spec.xKey) : "label",
          yKey: spec.yKey ? normalizeKey(spec.yKey) : "value",
          data: spec.data.map((row) => {
            const next: Record<string, unknown> = {};
            for (const [key, value] of Object.entries(row)) {
              next[normalizeKey(key)] = value;
            }
            return next;
          }),
          series: (spec.series ?? []).map((series) => ({
            ...series,
            key: normalizeKey(series.key),
          })),
        };
      case "pdf":
        return {
          ...spec,
          blocks: spec.blocks.map((block) => {
            if ((block.type === "line_item" || block.type === "total") && typeof block.amount === "number") {
              return {
                ...block,
                rawAmount: block.rawAmount ?? formatMoney(block.amount, block.currency ?? "TRY"),
                currency: block.currency ?? "TRY",
              };
            }
            return block;
          }),
        };
      case "svg":
        return {
          ...spec,
          canvas: {
            ...spec.canvas,
            viewBox: spec.canvas.viewBox || `0 0 ${spec.canvas.width} ${spec.canvas.height}`,
          },
        };
      default:
        return spec;
    }
  })();

  return artifactSpecSchema.parse(normalized);
}
