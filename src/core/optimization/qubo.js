function variableId(leftId, rightId) {
  return `x_${leftId}__${rightId}`.replace(/[^a-zA-Z0-9_]/g, '_');
}

function addLinear(qubo, key, value) {
  qubo.linear[key] = (qubo.linear[key] ?? 0) + value;
}

function addQuadratic(qubo, left, right, value) {
  const key = left < right ? `${left}|${right}` : `${right}|${left}`;
  qubo.quadratic[key] = (qubo.quadratic[key] ?? 0) + value;
}

function addExactlyOnePenalty(qubo, ids, penalty) {
  qubo.offset += penalty;
  for (const id of ids) addLinear(qubo, id, -penalty);
  for (let i = 0; i < ids.length; i += 1) {
    for (let j = i + 1; j < ids.length; j += 1) {
      addQuadratic(qubo, ids[i], ids[j], 2 * penalty);
    }
  }
}

function addAtMostCapacityPenalty(qubo, ids, capacity, penalty) {
  if (ids.length <= capacity) return;

  if (capacity === 1) {
    for (let i = 0; i < ids.length; i += 1) {
      for (let j = i + 1; j < ids.length; j += 1) {
        addQuadratic(qubo, ids[i], ids[j], penalty);
      }
    }
    return;
  }

  for (let i = 0; i < ids.length; i += 1) {
    for (let j = i + 1; j < ids.length; j += 1) {
      addQuadratic(qubo, ids[i], ids[j], penalty / Math.max(1, capacity));
    }
  }
}

function buildQubo(problem) {
  const variables = [];
  const qubo = {
    variables,
    linear: {},
    quadratic: {},
    offset: 0,
    penalty: 25,
  };

  if (problem.problemType === 'resource_allocation') {
    for (const resource of problem.resources) {
      for (const location of problem.locations) {
        const id = variableId(resource.id, location.id);
        variables.push({ id, leftId: resource.id, rightId: location.id });
        const cost = problem.costs?.[resource.id]?.[location.id] ?? 999;
        addLinear(qubo, id, cost - location.priority * location.need);
      }
    }

    for (const location of problem.locations) {
      addExactlyOnePenalty(qubo, problem.resources.map((resource) => variableId(resource.id, location.id)), qubo.penalty);
    }

    for (const resource of problem.resources) {
      addAtMostCapacityPenalty(
        qubo,
        problem.locations.map((location) => variableId(resource.id, location.id)),
        resource.capacity ?? 1,
        qubo.penalty
      );
    }

    return qubo;
  }

  for (const worker of problem.workers) {
    for (const task of problem.tasks) {
      const id = variableId(worker.id, task.id);
      variables.push({ id, leftId: worker.id, rightId: task.id });
      const baseCost = problem.costs?.[worker.id]?.[task.id] ?? 999;
      const skillPenalty = task.requiredSkill && !worker.skills?.includes(task.requiredSkill) ? 100 : 0;
      addLinear(qubo, id, baseCost + skillPenalty);
    }
  }

  for (const task of problem.tasks) {
    addExactlyOnePenalty(qubo, problem.workers.map((worker) => variableId(worker.id, task.id)), qubo.penalty);
  }

  for (const worker of problem.workers) {
    addAtMostCapacityPenalty(
      qubo,
      problem.tasks.map((task) => variableId(worker.id, task.id)),
      worker.capacity ?? 1,
      qubo.penalty
    );
  }

  return qubo;
}

function evaluateQubo(qubo, bits) {
  let energy = qubo.offset;
  for (const variable of qubo.variables) {
    energy += (qubo.linear[variable.id] ?? 0) * (bits[variable.id] ? 1 : 0);
  }
  for (const [key, value] of Object.entries(qubo.quadratic)) {
    const [left, right] = key.split('|');
    energy += value * (bits[left] ? 1 : 0) * (bits[right] ? 1 : 0);
  }
  return energy;
}

module.exports = {
  buildQubo,
  evaluateQubo,
  variableId,
};
