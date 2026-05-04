/* eslint-disable @typescript-eslint/no-require-imports */
const { getProblemEntities } = require('./model.js');
const { rankSolverResults } = require('./solvers.js');

function buildComparisonSummary(results, selected) {
  const runnerUp = rankSolverResults(results)[1];

  return {
    solverCount: results.length,
    feasibleSolverCount: results.filter((result) => result.feasible).length,
    selectedSolver: selected.solver,
    selectedBackend: selected.backend,
    selectedCost: selected.totalCost,
    runnerUpCost: runnerUp ? runnerUp.totalCost : null,
    costGapToRunnerUp: runnerUp ? Math.max(0, runnerUp.totalCost - selected.totalCost) : 0,
    selectedEnergy: selected.energy,
    explanation: selected.explanation,
  };
}

function buildOptimizationPipeline(problem, model, qubo, results, selected) {
  const entities = getProblemEntities(problem);
  const comparisonSummary = buildComparisonSummary(results, selected);

  return [
    {
      step: 'problem',
      title: 'Problem',
      summary: `Classified as ${problem.problemType} with ${entities.leftEntities.length} ${entities.leftEntityKind}s and ${entities.rightEntities.length} ${entities.rightEntityKind}s.`,
    },
    {
      step: 'model',
      title: 'Model',
      summary: `Built an explicit binary model with ${model.variables} decision variables and ${model.constraints.length} hard constraints.`,
    },
    {
      step: 'constraint',
      title: 'Constraint',
      summary: model.constraints.join(' '),
    },
    {
      step: 'objective',
      title: 'Objective',
      summary: model.objective,
    },
    {
      step: 'representation',
      title: 'Representation',
      summary: `Encoded the problem as a QUBO with ${qubo.variables.length} variables, ${Object.keys(qubo.linear).length} linear terms, and ${Object.keys(qubo.quadratic).length} quadratic terms.`,
    },
    {
      step: 'solve',
      title: 'Solve',
      summary: `Compared ${results.length} solvers (${comparisonSummary.feasibleSolverCount} feasible) across classical and quantum-inspired paths.`,
    },
    {
      step: 'compare',
      title: 'Compare',
      summary:
        comparisonSummary.runnerUpCost === null
          ? `Selected ${selected.solver} as the best available solution.`
          : `Selected ${selected.solver} because it beats the next best candidate by ${comparisonSummary.costGapToRunnerUp}.`,
    },
    {
      step: 'explain',
      title: 'Explain',
      summary: selected.feasible
        ? `Chosen solution is feasible with total cost ${selected.totalCost} and zero constraint violations.`
        : `Chosen solution is the strongest available fallback with ${selected.violationCount} constraint violations.`,
    },
  ];
}

function buildMarkdownReport(problem, model, qubo, results, selected) {
  const pipeline = buildOptimizationPipeline(problem, model, qubo, results, selected);
  const comparisonSummary = buildComparisonSummary(results, selected);
  const rows = results
    .map((result) => `| ${result.solver} | ${result.backend} | ${result.feasible ? 'yes' : 'no'} | ${result.totalCost} | ${result.energy.toFixed(2)} | ${result.violationCount} | ${result.runtimeMs}ms |`)
    .join('\n');
  const assignmentLines = selected.assignments
    .map((item) => `- ${item.from} -> ${item.to} (cost ${item.cost})`)
    .join('\n');

  return [
    '# Optimization Decision Report',
    '',
    `Problem: ${problem.title ?? model.problemType}`,
    `Type: ${model.problemType}`,
    '',
    '## Problem Model',
    `Objective: ${model.objective}`,
    `Binary variables: ${model.variables}`,
    `Constraints: ${model.constraints.join(' ')}`,
    '',
    '## Decision Pipeline',
    ...pipeline.map((entry) => `- **${entry.title}**: ${entry.summary}`),
    '',
    '## Problem Representation',
    `Binary variables: ${qubo.variables.length}`,
    `Linear terms: ${Object.keys(qubo.linear).length}`,
    `Quadratic terms: ${Object.keys(qubo.quadratic).length}`,
    `Penalty weight: ${qubo.penalty}`,
    '',
    '## Solver Comparison',
    '| Solver | Backend | Feasible | Cost | QUBO energy | Violations | Runtime |',
    '| --- | --- | --- | ---: | ---: | ---: | ---: |',
    rows,
    '',
    `Feasible solvers: ${comparisonSummary.feasibleSolverCount}/${comparisonSummary.solverCount}`,
    `Cost gap to next best solver: ${comparisonSummary.runnerUpCost === null ? 'n/a' : comparisonSummary.costGapToRunnerUp}`,
    '',
    '## Recommended Solution',
    `Selected solver: ${selected.solver}`,
    `Total cost: ${selected.totalCost}`,
    `Constraint violations: ${selected.violationCount}`,
    assignmentLines,
    '',
    '## Why This Solution',
    selected.feasible
      ? 'This solution was selected because it is feasible and has the lowest cost among the compared solver outputs.'
      : 'No fully feasible solution was found; this output has the lowest violation count and cost among available solver outputs.',
    selected.explanation ? `Solver explanation: ${selected.explanation}` : '',
    '',
    '## Technical Summary',
    `QUBO variables: ${qubo.variables.length}. Linear terms: ${Object.keys(qubo.linear).length}. Quadratic terms: ${Object.keys(qubo.quadratic).length}. No real quantum hardware was used; the quantum-inspired path uses QUBO search and simulated annealing.`,
  ].join('\n');
}

module.exports = {
  buildComparisonSummary,
  buildMarkdownReport,
  buildOptimizationPipeline,
};
