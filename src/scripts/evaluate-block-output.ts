import { evaluateBlockOutputPolicyFixtures } from "../core/understanding/block-output-evaluator.js";

function pct(value: number): string {
  return `${(value * 100).toFixed(1)}%`;
}

const summary = await evaluateBlockOutputPolicyFixtures();

console.log("Elyan block output evaluator");
console.log(`fixtures:              ${summary.fixtureCount}`);
console.log(`pass / fail:           ${summary.passCount} / ${summary.failCount}`);
console.log(`route accuracy:        ${pct(summary.routeAccuracy)}`);
console.log(`shape accuracy:        ${pct(summary.shapeAccuracy)}`);
console.log(`schema valid rate:     ${pct(summary.schemaValidRate)}  (min 95%)`);
console.log(`duplicate table rate:  ${pct(summary.duplicateTableRate)}  (max 0%)`);
console.log(`raw JSON leak rate:    ${pct(summary.rawJsonLeakRate)}  (max 0%)`);
console.log(`avg quality score:     ${summary.averageQualityScore.toFixed(1)}  (min 95)`);

if (!summary.ciPass) {
  console.log("CI: FAIL");
  for (const violation of summary.ciViolations) {
    console.log(`- ${violation}`);
  }
  process.exit(1);
}

console.log("CI: PASS");
