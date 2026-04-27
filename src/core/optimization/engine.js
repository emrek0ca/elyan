/* eslint-disable @typescript-eslint/no-require-imports */
const { buildAssignmentDemo, buildResourceAllocationDemo, normalizeProblem } = require('./demos.js');
const { buildModelSummary, buildProblemProfile } = require('./model.js');
const { buildQubo } = require('./qubo.js');
const { selectBestResult, solveWithBuiltInSolvers } = require('./solvers.js');
const {
  buildComparisonSummary,
  buildMarkdownReport,
  buildOptimizationPipeline,
} = require('./report.js');

function runOptimization(input = {}) {
  const problem = normalizeProblem(input);
  const model = buildModelSummary(problem);
  const qubo = buildQubo(problem);
  const results = solveWithBuiltInSolvers(problem, qubo);
  const selected = selectBestResult(results);
  const problemProfile = buildProblemProfile(problem, qubo, model);
  const pipeline = buildOptimizationPipeline(problem, model, qubo, results, selected);
  const comparisonSummary = buildComparisonSummary(results, selected);
  const markdownReport = buildMarkdownReport(problem, model, qubo, results, selected);

  return {
    ok: true,
    action: input.action ?? 'run_demo',
    problem,
    problemProfile,
    model,
    pipeline,
    comparisonSummary,
    qubo,
    solverResults: results,
    selectedSolution: selected,
    markdownReport,
    jsonSummary: {
      problemType: model.problemType,
      selectedSolver: selected.solver,
      selectedBackend: selected.backend,
      feasible: selected.feasible,
      totalCost: selected.totalCost,
      violationCount: selected.violationCount,
      assignmentCount: selected.assignments.length,
    },
  };
}

module.exports = {
  buildAssignmentDemo,
  buildResourceAllocationDemo,
  buildQubo,
  runOptimization,
};
