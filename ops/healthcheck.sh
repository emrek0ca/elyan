#!/bin/bash
set -euo pipefail

BASE_URL="${ELYAN_BASE_URL:-http://127.0.0.1:${PORT:-3000}}"
HEALTH_URL="${ELYAN_HEALTH_URL:-$BASE_URL/api/healthz}"
CONTROL_PLANE_HEALTH_URL="${ELYAN_CONTROL_PLANE_HEALTH_URL:-$BASE_URL/api/control-plane/health}"
MODELS_URL="${ELYAN_MODELS_URL:-$BASE_URL/api/models}"

node - "$HEALTH_URL" "$CONTROL_PLANE_HEALTH_URL" "$MODELS_URL" <<'NODE'
const [healthUrl, controlPlaneHealthUrl, modelsUrl] = process.argv.slice(2);
const timeoutMs = Number(process.env.ELYAN_HEALTHCHECK_TIMEOUT_MS || '5000');

async function probeJson(url, label) {
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), timeoutMs);

  try {
    const response = await fetch(url, { signal: controller.signal });
    if (!response.ok) {
      throw new Error(`${label} returned ${response.status}`);
    }

    return await response.json();
  } catch (error) {
    const message = error instanceof Error ? error.message : `Unable to reach ${label}`;
    throw new Error(`${label} probe failed: ${message}`);
  } finally {
    clearTimeout(timer);
  }
}

async function main() {
  const health = await probeJson(healthUrl, 'healthz');
  if (!health || health.ok !== true) {
    throw new Error('healthz did not report ok=true');
  }

  const controlPlane = await probeJson(controlPlaneHealthUrl, 'control-plane health');
  if (!controlPlane || controlPlane.ok !== true) {
    throw new Error('control-plane health did not report ok=true');
  }

  if (process.env.DATABASE_URL && controlPlane.storage !== 'postgres') {
    throw new Error(`control-plane storage expected postgres but reported ${String(controlPlane.storage)}`);
  }

  const models = await probeJson(modelsUrl, 'models');
  if (!models || !Array.isArray(models.models) || models.models.length === 0) {
    throw new Error('models endpoint did not return any available models');
  }

  console.log(`✅ Elyan healthcheck passed: ${healthUrl}`);
  console.log(`✅ Elyan control-plane check passed: ${controlPlaneHealthUrl}`);
  console.log(`✅ Elyan models check passed: ${models.models.length} model(s) available`);
}

main().catch((error) => {
  console.error(`❌ Elyan healthcheck failed: ${error instanceof Error ? error.message : String(error)}`);
  process.exit(1);
});
NODE
