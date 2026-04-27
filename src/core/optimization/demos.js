function buildAssignmentDemo() {
  return {
    problemType: 'assignment',
    title: 'TEKNOFEST assignment demo',
    tasks: [
      { id: 'drone-routing', title: 'Drone routing model', requiredSkill: 'routing' },
      { id: 'vision-qc', title: 'Vision quality check', requiredSkill: 'vision' },
      { id: 'reporting', title: 'Decision report', requiredSkill: 'reporting' },
    ],
    workers: [
      { id: 'ayla', title: 'Ayla', capacity: 1, skills: ['routing', 'reporting'] },
      { id: 'mert', title: 'Mert', capacity: 2, skills: ['vision', 'routing'] },
      { id: 'deniz', title: 'Deniz', capacity: 1, skills: ['reporting', 'vision'] },
    ],
    costs: {
      ayla: { 'drone-routing': 4, 'vision-qc': 9, reporting: 3 },
      mert: { 'drone-routing': 5, 'vision-qc': 2, reporting: 7 },
      deniz: { 'drone-routing': 8, 'vision-qc': 4, reporting: 2 },
    },
  };
}

function buildResourceAllocationDemo() {
  return {
    problemType: 'resource_allocation',
    title: 'TEKNOFEST disaster response allocation demo',
    resources: [
      { id: 'truck-a', title: 'Truck A', capacity: 2 },
      { id: 'truck-b', title: 'Truck B', capacity: 1 },
      { id: 'medical-team', title: 'Medical Team', capacity: 1 },
    ],
    locations: [
      { id: 'zone-1', title: 'Zone 1', need: 1, priority: 10 },
      { id: 'zone-2', title: 'Zone 2', need: 1, priority: 8 },
      { id: 'zone-3', title: 'Zone 3', need: 1, priority: 6 },
    ],
    costs: {
      'truck-a': { 'zone-1': 3, 'zone-2': 6, 'zone-3': 4 },
      'truck-b': { 'zone-1': 5, 'zone-2': 3, 'zone-3': 7 },
      'medical-team': { 'zone-1': 4, 'zone-2': 5, 'zone-3': 2 },
    },
  };
}

function normalizeProblem(input = {}) {
  if (input.problem) return input.problem;
  if (input.demo === 'resource-allocation' || input.demo === 'resource_allocation') return buildResourceAllocationDemo();
  return buildAssignmentDemo();
}

module.exports = {
  buildAssignmentDemo,
  buildResourceAllocationDemo,
  normalizeProblem,
};
