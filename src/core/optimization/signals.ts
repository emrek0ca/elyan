const OPTIMIZATION_QUERY_PATTERNS = [
  /\b(optimization|optimisation|optimize|optimise|qubo|ising|quantum-inspired|quantum inspired|hybrid solution|kuantum-esinli|hibrit çözüm)\b/i,
  /\b(assignment|task allocation|task assignment|resource allocation|resource distribution|best allocation|best distribution|minimum cost|minimum-cost|load balancing|routing|scheduling)\b/i,
  /\b(route optimization|route optimise|route optimize|rota optimizasyonu|en düşük maliyet|en iyi dağıtım|en verimli plan|görev dağıtımı|kaynak tahsisi)\b/i,
];

const RESOURCE_ALLOCATION_QUERY_PATTERNS = [
  /\b(resource allocation|resource distribution|best distribution|load balancing|capacity planning|fleet allocation|logistics allocation|disaster relief|relief allocation)\b/i,
  /\b(kaynak tahsisi|kaynakları dağıt|yük dengeleme|afet tahsisi|acil durum tahsisi|lojistik dağıtım|görevleri dağıt|kaynakları planla)\b/i,
];

export function isOptimizationQuery(query: string) {
  return OPTIMIZATION_QUERY_PATTERNS.some((pattern) => pattern.test(query));
}

export function isResourceAllocationOptimizationQuery(query: string) {
  return RESOURCE_ALLOCATION_QUERY_PATTERNS.some((pattern) => pattern.test(query));
}
