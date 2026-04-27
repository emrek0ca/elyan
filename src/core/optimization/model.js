function getProblemEntities(problem) {
  if (problem.problemType === 'resource_allocation') {
    return {
      leftEntityKind: 'resource',
      leftEntities: problem.resources,
      rightEntityKind: 'location',
      rightEntities: problem.locations,
    };
  }

  return {
    leftEntityKind: 'worker',
    leftEntities: problem.workers,
    rightEntityKind: 'task',
    rightEntities: problem.tasks,
  };
}

function buildModelSummary(problem) {
  if (problem.problemType === 'resource_allocation') {
    return {
      problemType: problem.problemType,
      variables: problem.resources.length * problem.locations.length,
      constraints: [
        'Each priority location receives exactly one resource.',
        'Each resource must stay within capacity.',
      ],
      objective: 'Minimize delivery cost while prioritizing high-need locations.',
    };
  }

  return {
    problemType: 'assignment',
    variables: problem.workers.length * problem.tasks.length,
    constraints: [
      'Each task is assigned exactly once.',
      'Each worker must stay within capacity.',
      'Required skills are treated as hard feasibility constraints.',
    ],
    objective: 'Minimize assignment cost without violating capacity or skill constraints.',
  };
}

function buildProblemProfile(problem, qubo, model) {
  const entities = getProblemEntities(problem);

  return {
    problemType: problem.problemType,
    leftEntityKind: entities.leftEntityKind,
    leftEntityCount: entities.leftEntities.length,
    rightEntityKind: entities.rightEntityKind,
    rightEntityCount: entities.rightEntities.length,
    decisionVariableCount: qubo.variables.length,
    hardConstraintCount: model.constraints.length,
  };
}

module.exports = {
  buildModelSummary,
  buildProblemProfile,
  getProblemEntities,
};
