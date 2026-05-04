# Optimization Lane

This lane keeps Elyan's optimization work local-first and honest: it models problems as binary optimization, compares classical and quantum-inspired solvers, and returns an explainable decision report.

## Module Boundaries

- `signals.ts`: shared intent detection for planner, skill selection, and operator preflight.
- `demos.js`: built-in local demo problems.
- `model.js`: problem entities, model summaries, and public profiles.
- `qubo.js`: QUBO variable construction and energy evaluation.
- `solvers.js`: built-in solver implementations and result ranking.
- `report.js`: decision pipeline, comparison summary, and Markdown report.
- `engine.js`: orchestration facade used by capability, bridge tool, CLI, and tests.

## Extension Rule

Add new problem types by extending the model, QUBO, solver evaluation, and report layers in that order. Keep optional external solvers optional; the lane must keep working without Qiskit, PennyLane, cloud APIs, or real quantum hardware.
