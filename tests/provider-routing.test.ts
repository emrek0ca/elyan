import { describe, expect, it } from 'vitest';
import { resolvePreferredModelIdFromAvailableModels } from '@/core/providers/routing';
import type { ModelInfo } from '@/types/provider';

const models: ModelInfo[] = [
  { id: 'ollama:llama3.2', name: 'llama3.2', provider: 'ollama', type: 'local' },
  { id: 'openai:gpt-4o', name: 'gpt-4o', provider: 'openai', type: 'cloud' },
];

describe('Provider routing', () => {
  it('keeps local-first routing on local models when no preference is given', () => {
    expect(resolvePreferredModelIdFromAvailableModels(models, undefined, 'local_first')).toBe('ollama:llama3.2');
  });

  it('prefers cloud models when cloud-preferred routing is requested', () => {
    expect(resolvePreferredModelIdFromAvailableModels(models, undefined, 'cloud_preferred')).toBe('openai:gpt-4o');
  });

  it('falls back to local models when cloud-preferred routing has no cloud models', () => {
    expect(
      resolvePreferredModelIdFromAvailableModels([models[0] as ModelInfo], undefined, 'cloud_preferred')
    ).toBe('ollama:llama3.2');
  });

  it('uses balanced routing to prefer cloud models for deep research work', () => {
    expect(
      resolvePreferredModelIdFromAvailableModels(models, {
        routingMode: 'balanced',
        taskIntent: 'research',
        reasoningDepth: 'deep',
      })
    ).toBe('openai:gpt-4o');
  });

  it('keeps team routing on local models unless cloud escalation is explicit', () => {
    expect(
      resolvePreferredModelIdFromAvailableModels(models, {
        routingMode: 'local_first',
        taskIntent: 'research',
        reasoningDepth: 'deep',
      })
    ).toBe('ollama:llama3.2');
  });

  it('enforces local-only routing for personal team workflow work', () => {
    expect(
      resolvePreferredModelIdFromAvailableModels(models, {
        routingMode: 'local_only',
        taskIntent: 'personal_workflow',
        reasoningDepth: 'standard',
      })
    ).toBe('ollama:llama3.2');
  });
});
