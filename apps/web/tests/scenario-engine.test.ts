import { describe, expect, it, vi } from 'vitest';

vi.mock('@/lib/env', () => ({
  env: {
    ELYAN_MODE: 'development',
  },
}));

import { matchScenario, resolveScenarioRequest, runScenarioBenchmark } from '@/core/scenarios';

describe('scenario engine', () => {
  it('maps delivery routing text to the logistics_routing scenario', () => {
    const match = matchScenario('optimize delivery routes');

    expect(match.matched).toBe(true);
    expect(match.scenarioId).toBe('logistics_routing');
    expect(match.type).toBe('routing');
    expect(match.confidence).toBeGreaterThan(0.5);
  });

  it('uses the predefined logistics scenario when demo mode has no input', () => {
    const resolution = resolveScenarioRequest(undefined, { mode: 'demo' });

    expect(resolution.status).toBe('ready');
    if (resolution.status !== 'ready') {
      throw new Error('expected demo scenario resolution to be ready');
    }

    expect(resolution.scenario.id).toBe('logistics_routing');
    expect(resolution.usesExampleInput).toBe(true);
    expect(resolution.input.nodes).toEqual(expect.arrayContaining(['depot', 'north', 'central', 'south']));
  });

  it('benchmarks baseline, classical, and hybrid candidates for demo logistics runs', () => {
    const result = runScenarioBenchmark('demo logistics', { mode: 'demo' });

    expect(result.status).toBe('ready');
    if (result.status !== 'ready') {
      throw new Error('expected scenario benchmark to be ready');
    }

    expect(result.scenario.id).toBe('logistics_routing');
    expect(result.baseline.solver).toBe('naive_baseline');
    expect(result.classical.solver).toBe('nearest_neighbor');
    expect(result.hybridResult.status).toBe('solved');
    expect(result.improvementPercent).toBeGreaterThanOrEqual(0);
    expect(result.efficiencyGain).toBeGreaterThanOrEqual(0);
    expect(result.constraintSatisfaction).toBeGreaterThanOrEqual(0);
    expect(result.markdownReport).toContain('Scenario Benchmark');
    expect(result.markdownReport).toContain('## Baseline vs Classical vs Hybrid');
  });

  it('keeps competition mode strict without auto-filling demo input', () => {
    const result = runScenarioBenchmark('demo logistics', { mode: 'competition' });

    expect(result.status).toBe('needs_input');
    if (result.status !== 'needs_input') {
      throw new Error('expected competition mode to require explicit input');
    }

    expect(result.scenario?.id).toBe('logistics_routing');
    expect(result.missing).toEqual(expect.arrayContaining(['nodes', 'costMatrix']));
  });
});
