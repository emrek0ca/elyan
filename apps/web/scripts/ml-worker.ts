#!/usr/bin/env node

import { spawn } from 'child_process';
import path from 'path';
import { mkdir, readFile, writeFile } from 'fs/promises';
import { Pool } from 'pg';
import {
  type MlDatabaseLearningEventRow,
} from '../src/core/ml';

type Mode = 'dataset' | 'train' | 'worker';

type MlWorkerConfig = {
  databaseUrl: string;
  storageDir: string;
  datasetsDir: string;
  modelsDir: string;
  runsDir: string;
  baseModel: string;
  intervalSeconds: number;
  maxSamples: number;
  trainingThreshold: number;
  minScore: number;
};

type QualityDatasetRow = {
  input: string;
  output: string;
  better_output: string;
  reasoning_trace: string[];
  score: number;
};

function parseArg(name: string, fallback?: string) {
  const index = process.argv.findIndex((arg) => arg === name);
  if (index === -1) {
    return fallback;
  }

  const next = process.argv[index + 1];
  return next && !next.startsWith('-') ? next : fallback;
}

function parseInteger(value: string | undefined, fallback: number) {
  const parsed = Number.parseInt(String(value ?? ''), 10);
  return Number.isFinite(parsed) && parsed > 0 ? parsed : fallback;
}

function resolveConfig(): MlWorkerConfig {
  const storageRoot =
    process.env.ELYAN_ML_OUTPUT_DIR?.trim() ||
    (process.env.ELYAN_STORAGE_DIR?.trim()
      ? path.join(process.env.ELYAN_STORAGE_DIR.trim(), 'ml')
      : path.resolve(process.cwd(), 'storage', 'ml'));
  return {
    databaseUrl: process.env.DATABASE_URL?.trim() || '',
    storageDir: storageRoot,
    datasetsDir: path.join(storageRoot, 'datasets'),
    modelsDir: path.join(storageRoot, 'models'),
    runsDir: path.join(storageRoot, 'runs'),
    baseModel: process.env.ELYAN_ML_BASE_MODEL?.trim() || 'distilgpt2',
    intervalSeconds: parseInteger(process.env.ELYAN_ML_INTERVAL_SECONDS, 1800),
    maxSamples: parseInteger(parseArg('--limit', process.env.ELYAN_ML_MAX_SAMPLES), 500),
    trainingThreshold: parseInteger(parseArg('--threshold', process.env.ELYAN_ML_TRAINING_THRESHOLD), 20),
    minScore: Number.parseFloat(parseArg('--min-score', process.env.ELYAN_ML_MIN_SCORE) ?? '0.6') || 0.6,
  };
}

async function ensureDirectories(config: MlWorkerConfig) {
  await mkdir(config.storageDir, { recursive: true });
  await mkdir(config.datasetsDir, { recursive: true });
  await mkdir(config.modelsDir, { recursive: true });
  await mkdir(config.runsDir, { recursive: true });
}

async function queryLearningEvents(pool: Pool) {
  const result = await pool.query<MlDatabaseLearningEventRow>(`
    SELECT
      event_id,
      account_id,
      request_id,
      source,
      input,
      intent,
      plan,
      reasoning_steps,
      reasoning_trace,
      output,
      better_output,
      success,
      failure_reason,
      latency_ms,
      score,
      accepted,
      model_id,
      model_provider,
      metadata,
      created_at
    FROM learning_events
    ORDER BY created_at DESC, event_id DESC
  `);

  return result.rows;
}

async function writeJson(pathname: string, payload: unknown) {
  await writeFile(pathname, `${JSON.stringify(payload, null, 2)}\n`, 'utf8');
}

async function writeJsonl(pathname: string, records: QualityDatasetRow[]) {
  const content = records.map((record) => JSON.stringify(record)).join('\n');
  await writeFile(pathname, `${content}${content.length > 0 ? '\n' : ''}`, 'utf8');
}

async function loadDatasetSnapshot(config: MlWorkerConfig) {
  const summaryPath = path.join(config.datasetsDir, 'latest.summary.json');

  try {
    const summaryText = await readFile(summaryPath, 'utf8');

    return {
      summary: JSON.parse(summaryText) as Record<string, unknown>,
    };
  } catch {
    return null;
  }
}

async function buildDataset(config: MlWorkerConfig) {
  if (!config.databaseUrl) {
    throw new Error('DATABASE_URL is required for ml:dataset');
  }

  await ensureDirectories(config);
  const pool = new Pool({ connectionString: config.databaseUrl });
  try {
    const learningEvents = await queryLearningEvents(pool);
    const acceptedEvents = learningEvents.filter((event) => event.accepted === true && Number(event.score ?? 0) >= config.minScore);
    const rows: QualityDatasetRow[] = acceptedEvents.slice(0, config.maxSamples).map((event) => ({
      input: String(event.input ?? ''),
      output: String(event.output ?? ''),
      better_output: String(event.better_output ?? event.output ?? ''),
      reasoning_trace: Array.isArray(event.reasoning_trace)
        ? event.reasoning_trace.filter((step): step is string => typeof step === 'string' && step.trim().length > 0)
        : Array.isArray(event.reasoning_steps)
          ? event.reasoning_steps.filter((step): step is string => typeof step === 'string' && step.trim().length > 0)
          : [],
      score: Number(event.score ?? 0),
    }));

    const timestamp = new Date().toISOString().replace(/[:.]/g, '-');
    const runDir = path.join(config.runsDir, timestamp);
    await mkdir(runDir, { recursive: true });

    const datasetPath = path.join(config.datasetsDir, 'latest.jsonl');
    const summaryPath = path.join(config.datasetsDir, 'latest.summary.json');
    const manifestPath = path.join(runDir, 'dataset-manifest.json');
    const totalScore = rows.reduce((sum, row) => sum + row.score, 0);
    const averageScore = rows.length > 0 ? Number((totalScore / rows.length).toFixed(2)) : 0;
    const discardedCount = Math.max(0, learningEvents.length - rows.length);
    const discardRate = learningEvents.length > 0 ? Number((discardedCount / learningEvents.length).toFixed(2)) : 0;
    const summary = {
      record_count: rows.length,
      accepted_count: rows.length,
      discarded_count: discardedCount,
      discard_rate: discardRate,
      average_score: averageScore,
      clean_data_only: true,
      minimum_score: config.minScore,
      quality_metrics: {
        average_score: averageScore,
        discard_rate: discardRate,
      },
      created_at: new Date().toISOString(),
    };

    await Promise.all([
      writeJsonl(datasetPath, rows),
      writeJson(summaryPath, {
        ...summary,
        dataset_path: datasetPath,
        run_dir: runDir,
        training_threshold: config.trainingThreshold,
        should_train: summary.record_count >= config.trainingThreshold,
      }),
      writeJson(manifestPath, {
        dataset_path: datasetPath,
        summary_path: summaryPath,
        model_strategy: 'quality_gate',
        max_samples: config.maxSamples,
        training_threshold: config.trainingThreshold,
        records: summary.record_count,
        created_at: new Date().toISOString(),
      }),
    ]);

    return {
      ok: true,
      dataset_path: datasetPath,
      summary_path: summaryPath,
      manifest_path: manifestPath,
      run_dir: runDir,
      ...summary,
    };
  } finally {
    await pool.end();
  }
}

function runPythonTraining(config: MlWorkerConfig, datasetPath: string, runDir: string) {
  const trainerPath = path.resolve(process.cwd(), 'scripts', 'ml-train.py');
  const modelVersion = `elyan-brain-v${new Date().toISOString().replace(/[:.]/g, '-')}`;
  const outputDir = path.join(config.modelsDir, modelVersion);
  const args = [
    trainerPath,
    '--dataset',
    datasetPath,
    '--output-dir',
    outputDir,
    '--base-model',
    config.baseModel,
    '--run-dir',
    runDir,
  ];

  return new Promise<Record<string, unknown>>((resolve, reject) => {
    const child = spawn('python3', args, {
      cwd: process.cwd(),
      env: process.env,
      stdio: ['ignore', 'pipe', 'pipe'],
    });

    let stdout = '';
    let stderr = '';
    child.stdout.on('data', (chunk) => {
      stdout += chunk.toString('utf8');
    });
    child.stderr.on('data', (chunk) => {
      stderr += chunk.toString('utf8');
    });
    child.on('error', reject);
    child.on('close', (code) => {
      if (code !== 0) {
        reject(new Error(stderr.trim() || `ml training failed with exit code ${code}`));
        return;
      }

      const trimmed = stdout.trim();
      if (!trimmed) {
        resolve({ ok: true, output_dir: outputDir, run_dir: runDir });
        return;
      }

      try {
        resolve(JSON.parse(trimmed) as Record<string, unknown>);
      } catch {
        resolve({
          ok: true,
          output_dir: outputDir,
          model_version: modelVersion,
          run_dir: runDir,
          raw_output: trimmed,
        });
      }
    });
  });
}

async function persistModelArtifact(
  config: MlWorkerConfig,
  trainingResult: Record<string, unknown>,
  datasetSummary: Record<string, unknown>
) {
  if (!config.databaseUrl || trainingResult.ok !== true || trainingResult.fallback === true) {
    return null;
  }

  const outputDir = typeof trainingResult.output_dir === 'string' ? trainingResult.output_dir : '';
  if (!outputDir) {
    return null;
  }

  const modelVersion =
    typeof trainingResult.model_version === 'string' && trainingResult.model_version.trim().length > 0
      ? trainingResult.model_version
      : path.basename(outputDir);
  const metrics = trainingResult.metrics && typeof trainingResult.metrics === 'object' ? (trainingResult.metrics as Record<string, unknown>) : {};
  const evalLoss = typeof metrics.eval_loss === 'number' && Number.isFinite(metrics.eval_loss) ? metrics.eval_loss : null;
  const trainLoss = typeof metrics.train_loss === 'number' && Number.isFinite(metrics.train_loss) ? metrics.train_loss : null;
  const score = evalLoss !== null ? Number((1 / (1 + Math.max(0, evalLoss))).toFixed(6)) : null;
  const pool = new Pool({ connectionString: config.databaseUrl });

  try {
    await pool.query('BEGIN');
    const activeResult = await pool.query<{
      model_version: string;
      score: number | string | null;
    }>(`
      SELECT model_version, score
      FROM model_artifacts
      WHERE active = true
      ORDER BY COALESCE(score, 0) DESC, updated_at DESC
      LIMIT 1
    `);
    const activeArtifact = activeResult.rows[0] ?? null;
    const activeScore = activeArtifact?.score !== null && activeArtifact?.score !== undefined ? Number(activeArtifact.score) : null;
    const shouldPromote =
      score !== null && (!activeArtifact || activeScore === null || (Number.isFinite(activeScore) && score > activeScore));

    if (shouldPromote) {
      await pool.query(`UPDATE model_artifacts SET active = false, updated_at = NOW() WHERE active = true`);
    }

    await pool.query(
      `
        INSERT INTO model_artifacts (
          model_version,
          base_model,
          dataset_size,
          loss,
          score,
          active,
          artifact_path,
          metadata,
          created_at,
          updated_at
        )
        VALUES ($1, $2, $3, $4::numeric, $5::numeric, $6, $7, $8::jsonb, NOW(), NOW())
        ON CONFLICT (model_version) DO UPDATE SET
          base_model = EXCLUDED.base_model,
          dataset_size = EXCLUDED.dataset_size,
          loss = EXCLUDED.loss,
          score = EXCLUDED.score,
          active = EXCLUDED.active,
          artifact_path = EXCLUDED.artifact_path,
          metadata = EXCLUDED.metadata,
          updated_at = EXCLUDED.updated_at
      `,
      [
        modelVersion,
        config.baseModel,
        Number(datasetSummary.record_count ?? 0),
        evalLoss,
        score,
        shouldPromote,
        outputDir,
        JSON.stringify({
          dataset_summary: datasetSummary,
          train_loss: trainLoss,
          eval_loss: evalLoss,
          score,
          promoted: shouldPromote,
          created_at: new Date().toISOString(),
        }),
      ]
    );

    if (shouldPromote) {
      await pool.query(`UPDATE model_artifacts SET active = true, updated_at = NOW() WHERE model_version = $1`, [modelVersion]);
    }

    await pool.query('COMMIT');

    await writeJson(path.join(outputDir, 'model-manifest.json'), {
      ok: true,
      model_version: modelVersion,
      base_model: config.baseModel,
      dataset_size: Number(datasetSummary.record_count ?? 0),
      loss: evalLoss,
      score,
      active: shouldPromote,
      artifact_path: outputDir,
      created_at: new Date().toISOString(),
      dataset_summary: datasetSummary,
      metrics,
    });

    return {
      model_version: modelVersion,
      artifact_path: outputDir,
      loss: evalLoss,
      score,
      active: shouldPromote,
    };
  } finally {
    try {
      await pool.query('ROLLBACK');
    } catch {
      // ignore when no transaction is open
    }
    await pool.end();
  }
}

async function trainDataset(config: MlWorkerConfig) {
  let snapshot = await loadDatasetSnapshot(config);
  if (!snapshot) {
    const dataset = await buildDataset(config);
    snapshot = {
      summary: dataset,
    };
  }

  const datasetPath = path.join(config.datasetsDir, 'latest.jsonl');
  const runDir = path.join(config.runsDir, new Date().toISOString().replace(/[:.]/g, '-'));
  await mkdir(runDir, { recursive: true });
  const result = await runPythonTraining(config, datasetPath, runDir).catch((error: unknown) => ({
    ok: false,
    fallback: true,
    error: error instanceof Error ? error.message : 'ml training failed',
    dataset_path: datasetPath,
    run_dir: runDir,
  }));

  const artifact = await persistModelArtifact(config, result, snapshot.summary).catch((error: unknown) => ({
    ok: false,
    error: error instanceof Error ? error.message : 'model artifact persistence failed',
  }));
  const trainingSuccess = Boolean(result.ok === true && result.fallback !== true);
  const inferenceSuccess = Boolean(artifact && (artifact as { active?: boolean }).active === true);

  await writeJson(path.join(runDir, 'training-report.json'), {
    ...result,
    dataset_path: datasetPath,
    run_dir: runDir,
    created_at: new Date().toISOString(),
    dataset_summary: snapshot.summary,
    quality_metrics: snapshot.summary.quality_metrics ?? {
      average_score: snapshot.summary.average_score,
      discard_rate: snapshot.summary.discard_rate,
    },
    training_success: trainingSuccess,
    inference_success: inferenceSuccess,
    model_artifact: artifact,
  });

  return {
    ...result,
    model_artifact: artifact,
    training_success: trainingSuccess,
    inference_success: inferenceSuccess,
  };
}

async function runWorker(config: MlWorkerConfig) {
  const intervalMs = Math.max(60_000, config.intervalSeconds * 1000);

  // Continuous worker: build dataset, train, then wait before the next cycle.
  // The service restarts on failure, so a clean exit is avoided unless the process is interrupted.
  // This keeps the worker self-healing while remaining deterministic.
  while (true) {
    const datasetResult = await buildDataset(config);
    const trainResult =
      Number(datasetResult.record_count ?? 0) >= config.trainingThreshold
        ? await trainDataset(config)
        : {
            ok: true,
            skipped: true,
            reason: `dataset size ${Number(datasetResult.record_count ?? 0)} is below threshold ${config.trainingThreshold}`,
            dataset_path: datasetResult.dataset_path,
            run_dir: datasetResult.run_dir,
          };
    const cycle = {
      ok: true,
      dataset: datasetResult,
      training: trainResult,
      quality_metrics: {
        average_score: datasetResult.average_score,
        discard_rate: datasetResult.discard_rate,
        training_success: Boolean((trainResult as { training_success?: boolean }).training_success),
        inference_success: Boolean((trainResult as { inference_success?: boolean }).inference_success),
      },
      completed_at: new Date().toISOString(),
    };
    const cyclePath = path.join(config.runsDir, 'latest-cycle.json');
    await writeJson(cyclePath, cycle);
    console.log(JSON.stringify(cycle, null, 2));
    await new Promise((resolve) => setTimeout(resolve, intervalMs));
  }
}

async function main() {
  const mode = (process.argv[2] as Mode | undefined) ?? 'worker';
  const config = resolveConfig();

  if (mode === 'dataset') {
    const result = await buildDataset(config);
    console.log(JSON.stringify(result, null, 2));
    return;
  }

  if (mode === 'train') {
    const result = await trainDataset(config);
    console.log(JSON.stringify(result, null, 2));
    return;
  }

  if (mode === 'worker') {
    await ensureDirectories(config);
    await runWorker(config);
    return;
  }

  throw new Error(`Unsupported ml worker mode: ${mode}`);
}

main().catch((error) => {
  console.error(error instanceof Error ? error.stack || error.message : String(error));
  process.exitCode = 1;
});
