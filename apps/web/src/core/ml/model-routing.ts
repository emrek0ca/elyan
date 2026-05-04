import { env } from '@/lib/env';
import { getControlPlanePool } from '@/core/control-plane/database';

type ModelArtifactRow = {
  model_version: string;
  dataset_size: number | string | null;
  artifact_path: string | null;
  loss: number | string | null;
  score: number | string | null;
  active: boolean | null;
};

async function readActiveModelArtifact(): Promise<ModelArtifactRow | null> {
  if (!env.DATABASE_URL) {
    return null;
  }

  try {
    const pool = getControlPlanePool(env.DATABASE_URL);
    const result = await pool.query<ModelArtifactRow>(`
      SELECT model_version, dataset_size, artifact_path, loss, score, active
      FROM model_artifacts
      WHERE active = true
      ORDER BY COALESCE(score, 0) DESC, updated_at DESC
      LIMIT 1
    `);

    return result.rows[0] ?? null;
  } catch {
    return null;
  }
}

export async function resolveBrainPreferredModelId() {
  const artifact = await readActiveModelArtifact();
  if (!artifact) {
    return null;
  }

  const datasetSize = Number(artifact.dataset_size ?? 0);
  if (!Number.isFinite(datasetSize) || datasetSize <= 0) {
    return null;
  }

  if (!artifact.artifact_path || String(artifact.artifact_path).trim().length === 0) {
    return null;
  }

  if (artifact.loss !== null && artifact.loss !== undefined && !Number.isFinite(Number(artifact.loss))) {
    return null;
  }

  if (artifact.score !== null && artifact.score !== undefined && !Number.isFinite(Number(artifact.score))) {
    return null;
  }

  if (artifact.active !== true) {
    return null;
  }

  return env.ELYAN_BRAIN_MODEL_ID?.trim() || 'ollama:elyan_brain';
}
