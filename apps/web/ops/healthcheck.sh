#!/bin/bash
set -euo pipefail

BASE_URL="${ELYAN_HEALTHCHECK_BASE_URL:-http://127.0.0.1:${PORT:-3000}}"
HEALTH_URL="${ELYAN_HEALTH_URL:-$BASE_URL/api/healthz}"
CONTROL_PLANE_HEALTH_URL="${ELYAN_CONTROL_PLANE_HEALTH_URL:-$BASE_URL/api/control-plane/health}"
MODELS_URL="${ELYAN_MODELS_URL:-$BASE_URL/api/models}"
AUTH_ME_URL="${ELYAN_AUTH_ME_URL:-$BASE_URL/api/control-plane/auth/me}"
PREVIEW_CHAT_URL="${ELYAN_PREVIEW_CHAT_URL:-$BASE_URL/api/preview/chat}"

node - "$HEALTH_URL" "$CONTROL_PLANE_HEALTH_URL" "$MODELS_URL" "$AUTH_ME_URL" "$PREVIEW_CHAT_URL" <<'NODE'
const [healthUrl, controlPlaneHealthUrl, modelsUrl, authMeUrl, previewChatUrl] = process.argv.slice(2);
const timeoutMs = Number(process.env.ELYAN_HEALTHCHECK_TIMEOUT_MS || '5000');
const previewTimeoutMs = Number(process.env.ELYAN_PREVIEW_HEALTHCHECK_TIMEOUT_MS || '25000');

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

async function probeAuthMe(url) {
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), timeoutMs);

  try {
    const response = await fetch(url, { signal: controller.signal });
    if (response.status !== 401) {
      throw new Error(`auth/me expected 401 but returned ${response.status}`);
    }

    const body = await response.json().catch(() => null);
    if (!body || body.ok !== false) {
      throw new Error('auth/me did not return the expected control-plane error envelope');
    }

    return body;
  } catch (error) {
    const message = error instanceof Error ? error.message : 'Unable to reach auth/me';
    throw new Error(`auth/me probe failed: ${message}`);
  } finally {
    clearTimeout(timer);
  }
}

async function probePreviewChat(url) {
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), previewTimeoutMs);

  try {
    const response = await fetch(url, {
      method: 'POST',
      headers: {
        'content-type': 'application/json',
        accept: 'text/event-stream, application/json',
      },
      body: JSON.stringify({
        messages: [{ role: 'user', content: 'ping' }],
      }),
      signal: controller.signal,
    });

    const contentType = response.headers.get('content-type') ?? '';
    if (response.status === 200 && contentType.includes('text/event-stream')) {
      return { ok: true, mode: 'sse' };
    }

    const bodyText = await response.text();
    let body = null;

    try {
      body = bodyText ? JSON.parse(bodyText) : null;
    } catch {
      body = null;
    }

    if (body && typeof body === 'object' && body.ok === false && typeof body.error === 'string') {
      return { ok: true, mode: 'json-error', status: response.status, code: typeof body.code === 'string' ? body.code : undefined };
    }

    throw new Error(
      `preview/chat returned an unexpected response (${response.status}, ${contentType || 'no content-type'})`
    );
  } catch (error) {
    const message = error instanceof Error ? error.message : 'Unable to reach preview/chat';
    throw new Error(`preview/chat probe failed: ${message}`);
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

  await probeAuthMe(authMeUrl);

  const models = await probeJson(modelsUrl, 'models');
  if (!models || !Array.isArray(models.models) || models.models.length === 0) {
    throw new Error('models endpoint did not return any available models');
  }

  await probePreviewChat(previewChatUrl);

  console.log(`✅ Elyan healthcheck passed: ${healthUrl}`);
  console.log(`✅ Elyan control-plane check passed: ${controlPlaneHealthUrl}`);
  console.log(`✅ Elyan auth/me check passed: ${authMeUrl}`);
  console.log(`✅ Elyan models check passed: ${models.models.length} model(s) available`);
  console.log(`✅ Elyan preview/chat check passed: ${previewChatUrl}`);
}

main().catch((error) => {
  console.error(`❌ Elyan healthcheck failed: ${error instanceof Error ? error.message : String(error)}`);
  process.exit(1);
});
NODE
