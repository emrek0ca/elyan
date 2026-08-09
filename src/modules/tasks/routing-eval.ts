import {
  matchDesktopCapabilitiesSemantically,
  type DesktopCapabilitySemanticMatch,
} from "./desktop-capability-ontology.js";
import {
  ROUTING_EVAL_CORPUS,
  type RoutingEvalCase,
} from "./routing-eval-corpus.js";

// Yönlendirme ölçümü. Tek amacı var: bir düzeltmenin gerçekten iyileştirme
// olduğunu sayıyla göstermek. Skor düşerse regresyon vardır — "sanırım
// düzeldi" demek zorunda kalmayalım diye buradadır.

// `expected: null` vakalarında sistemin EMİN OLMAMASI beklenir. Bu eşiğin
// üstünde bir skor "kendinden emin eşleşme" sayılır.
export const CONFIDENT_MATCH_SCORE = 0.34;

export type RoutingEvalFailure = {
  utterance: string;
  group: string;
  kind: "top1" | "top3" | "negative" | "overconfident";
  expected: string | null;
  got: string[];
  detail?: string;
};

export type RoutingEvalGroupScore = {
  group: string;
  total: number;
  top1: number;
};

export type RoutingEvalReport = {
  total: number;
  top1: number;
  top3: number;
  negativeViolations: number;
  criticalViolations: number;
  overconfident: number;
  top1Rate: number;
  top3Rate: number;
  failures: RoutingEvalFailure[];
  byGroup: RoutingEvalGroupScore[];
};

function rank(testCase: RoutingEvalCase): DesktopCapabilitySemanticMatch[] {
  return matchDesktopCapabilitiesSemantically({
    query: testCase.utterance,
    intent: testCase.intent ?? null,
    sideEffectLevel: testCase.sideEffectLevel ?? null,
    limit: 5,
    // Eşik bilinçli olarak düşük: neyin sıralandığını görmek istiyoruz,
    // erken filtreleme ölçümü kör eder.
    threshold: 0,
  });
}

function acceptable(testCase: RoutingEvalCase): Set<string> {
  const values = new Set<string>();
  if (testCase.expected) values.add(testCase.expected);
  for (const value of testCase.alsoAcceptable ?? []) values.add(value);
  return values;
}

export function runRoutingEval(
  corpus: RoutingEvalCase[] = ROUTING_EVAL_CORPUS,
): RoutingEvalReport {
  const failures: RoutingEvalFailure[] = [];
  const groups = new Map<string, { total: number; top1: number }>();
  let top1 = 0;
  let top3 = 0;
  let scored = 0;
  let negativeViolations = 0;
  let criticalViolations = 0;
  let overconfident = 0;

  for (const testCase of corpus) {
    const matches = rank(testCase);
    const ids = matches.map((match) => match.capability);
    const topThree = ids.slice(0, 3);
    const group = groups.get(testCase.group) ?? { total: 0, top1: 0 };

    if (testCase.expected === null) {
      const best = matches[0];
      if (best && best.score >= CONFIDENT_MATCH_SCORE) {
        overconfident += 1;
        failures.push({
          utterance: testCase.utterance,
          group: testCase.group,
          kind: "overconfident",
          expected: null,
          got: topThree,
          detail: `skor ${best.score} >= ${CONFIDENT_MATCH_SCORE}`,
        });
      }
    } else {
      scored += 1;
      group.total += 1;
      const ok = acceptable(testCase);
      if (ids[0] && ok.has(ids[0])) {
        top1 += 1;
        group.top1 += 1;
      } else {
        failures.push({
          utterance: testCase.utterance,
          group: testCase.group,
          kind: "top1",
          expected: testCase.expected,
          got: topThree,
        });
      }
      if (topThree.some((id) => ok.has(id))) {
        top3 += 1;
      } else {
        failures.push({
          utterance: testCase.utterance,
          group: testCase.group,
          kind: "top3",
          expected: testCase.expected,
          got: topThree,
        });
      }
    }

    // Rütbe önemli: bir yasaklı yeteneğin top-1'de olması YANLIŞ İŞİN
    // YÜRÜTÜLMESİ demektir (kritik). Aynı yeteneğin 3. sırada olması yalnız
    // planlayıcıya zayıf bir aday sızdırır (uyarı). İkisini tek sayıda
    // toplamak, hangisini düzelttiğimizi göremememize yol açıyordu.
    for (const forbidden of testCase.mustNotMatch ?? []) {
      const rank = topThree.indexOf(forbidden);
      if (rank < 0) continue;
      if (rank === 0) {
        criticalViolations += 1;
        failures.push({
          utterance: testCase.utterance,
          group: testCase.group,
          kind: "negative",
          expected: testCase.expected,
          got: topThree,
          detail: `KRİTİK — yasaklı yetenek top-1'de: ${forbidden}`,
        });
      } else {
        negativeViolations += 1;
      }
    }

    groups.set(testCase.group, group);
  }

  return {
    total: corpus.length,
    top1,
    top3,
    negativeViolations,
    criticalViolations,
    overconfident,
    top1Rate: scored > 0 ? Number((top1 / scored).toFixed(4)) : 0,
    top3Rate: scored > 0 ? Number((top3 / scored).toFixed(4)) : 0,
    failures,
    byGroup: [...groups.entries()]
      .map(([group, value]) => ({ group, total: value.total, top1: value.top1 }))
      .sort((left, right) => left.group.localeCompare(right.group)),
  };
}

export function formatRoutingEvalReport(report: RoutingEvalReport): string {
  const lines: string[] = [];
  lines.push(
    `top-1 ${report.top1}/${report.top1 + report.failures.filter((f) => f.kind === "top1").length} (${(report.top1Rate * 100).toFixed(1)}%)`,
  );
  lines.push(`top-3 oranı ${(report.top3Rate * 100).toFixed(1)}%`);
  lines.push(
    `KRİTİK ihlal (yasaklı yetenek top-1'de): ${report.criticalViolations}`,
  );
  lines.push(`zayıf ihlal (yasaklı yetenek 2-3. sırada): ${report.negativeViolations}`);
  lines.push(`aşırı özgüven (sohbet olmalıydı): ${report.overconfident}`);
  lines.push("");
  lines.push("grup bazında top-1:");
  for (const group of report.byGroup) {
    const rate = group.total > 0 ? (group.top1 / group.total) * 100 : 0;
    lines.push(
      `  ${group.group.padEnd(24)} ${group.top1}/${group.total}  ${rate.toFixed(0)}%`,
    );
  }
  const notable = report.failures.filter((failure) => failure.kind !== "top3");
  if (notable.length > 0) {
    lines.push("");
    lines.push("hatalar:");
    for (const failure of notable) {
      lines.push(
        `  [${failure.kind}] "${failure.utterance}" → bekleniyordu ${failure.expected ?? "(eşleşme yok)"}, geldi ${failure.got.join(", ")}${failure.detail ? ` (${failure.detail})` : ""}`,
      );
    }
  }
  return lines.join("\n");
}
