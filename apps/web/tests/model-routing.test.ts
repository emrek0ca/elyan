import { beforeEach, describe, expect, it, vi } from 'vitest';

const mockQuery = vi.fn();
const mockGetControlPlanePool = vi.fn(() => ({
  query: mockQuery,
}));

vi.mock('@/lib/env', () => ({
  env: {
    DATABASE_URL: 'postgres://example',
    ELYAN_BRAIN_MODEL_ID: 'ollama:elyan_brain',
  },
}));

vi.mock('@/core/control-plane/database', () => ({
  getControlPlanePool: mockGetControlPlanePool,
}));

describe('brain model routing', () => {
  beforeEach(() => {
    mockQuery.mockReset();
  });

  it('returns the brain model only when an active artifact exists', async () => {
    mockQuery.mockResolvedValueOnce({
      rows: [
        {
          model_version: 'elyan-brain-v1',
          dataset_size: '32',
          artifact_path: '/srv/elyan/storage/ml/models/elyan-brain-v1',
          loss: '0.42',
          score: '0.70',
          active: true,
        },
      ],
    });

    const { resolveBrainPreferredModelId } = await import('@/core/ml/model-routing');
    await expect(resolveBrainPreferredModelId()).resolves.toBe('ollama:elyan_brain');
  });

  it('falls back to LLM routing when no active artifact is present', async () => {
    mockQuery.mockResolvedValueOnce({
      rows: [],
    });

    const { resolveBrainPreferredModelId } = await import('@/core/ml/model-routing');
    await expect(resolveBrainPreferredModelId()).resolves.toBeNull();
  });
});
