import {
  buildAssistantChartBlock,
  buildAssistantTableBlock,
} from "../chat/message-blocks.js";
import type { FactAnswer } from "./types.js";

type SeriesRow = { date: string; value: number };

function readSeries(answer: FactAnswer | null | undefined): SeriesRow[] {
  const series = answer?.values?.series;
  if (!Array.isArray(series)) return [];
  return series.flatMap((entry) => {
    if (!entry || typeof entry !== "object" || Array.isArray(entry)) return [];
    const row = entry as Record<string, unknown>;
    const date = typeof row.date === "string" ? row.date : "";
    const candidate = row.value ?? row.usdPerOunce ?? row.rate ?? row.price;
    const value =
      typeof candidate === "number" && Number.isFinite(candidate)
        ? candidate
        : null;
    return /^\d{4}-\d{2}-\d{2}$/u.test(date) && value != null
      ? [{ date, value }]
      : [];
  });
}

export function buildFactOutputBlocks(input: {
  answer?: FactAnswer | null;
  tableRequested: boolean;
  chartRequested: boolean;
}): unknown[] {
  const series = readSeries(input.answer);
  if (series.length === 0) return [];
  const symbol = String(
    input.answer?.values?.label ??
      input.answer?.values?.symbol ??
      input.answer?.values?.seriesId ??
      "Veri",
  );
  const unit = String(
    input.answer?.values?.unit ??
      (input.answer?.providerId === "alpha_vantage_metals"
        ? "USD/ons"
        : "değer"),
  );
  const source = input.answer?.citation.sourceHost ?? "verified source";
  const blocks: unknown[] = [];
  if (input.tableRequested) {
    const table = buildAssistantTableBlock({
      columns: ["Tarih", unit],
      rows: series.map((row) => [row.date, row.value]),
      title: `${symbol} fiyat serisi`,
      caption: `Kaynak: ${source}`,
      summary: `${series.length} doğrulanmış günlük gözlem`,
    });
    if (table) blocks.push(table);
  }
  if (input.chartRequested) {
    const chart = buildAssistantChartBlock({
      chartType: "line",
      labels: series.map((row) => row.date),
      values: series.map((row) => row.value),
      seriesName: symbol,
      title: `${symbol} fiyat trendi`,
      xLabel: "Tarih",
      yLabel: unit,
      unit,
      caption: `Kaynak: ${source}`,
    });
    if (chart) blocks.push(chart);
  }
  return blocks;
}
