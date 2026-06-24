#!/usr/bin/env bash
set -euo pipefail

BASE_URL="${BASE_URL:-https://api.elyan.dev}"
DIRECT_HEALTHCHECK_URL="${DIRECT_HEALTHCHECK_URL:-}"
AUTH_BEARER_TOKEN="${AUTH_BEARER_TOKEN:-}"
DESKTOP_DEVICE_ID="${DESKTOP_DEVICE_ID:-}"
RUNTIME_BEARER_TOKEN="${RUNTIME_BEARER_TOKEN:-}"
CHAT_PROMPT="${CHAT_PROMPT:-V1 public chat smoke check. Reply with a short acknowledgement.}"
TASK_PROMPT="${TASK_PROMPT:-Create a desktop-required smoke task and return a short acknowledgement.}"
TASK_CAPABILITIES="${TASK_CAPABILITIES:-browser.control,document.read}"
CHAT_CAPABILITIES="${CHAT_CAPABILITIES:-}"

need() {
  command -v "$1" >/dev/null 2>&1 || {
    echo "Missing required command: $1" >&2
    exit 1
  }
}

need curl
need python3

json_pretty() {
  python3 -m json.tool
}

build_capability_json() {
  local csv="$1"
  python3 - "$csv" <<'PY'
import json
import sys

items = [item.strip() for item in sys.argv[1].split(",") if item.strip()]
print(json.dumps(items))
PY
}

fetch_json() {
  local label="$1"
  shift
  local output
  output="$(curl -fsS "$@")"
  echo "==> ${label}"
  printf '%s\n' "${output}" | json_pretty
  echo
}

probe_controlled_auth_failure() {
  local provider="$1"
  local body_file
  body_file="$(mktemp)"

  local status
  status="$(curl -sS -o "${body_file}" -w '%{http_code}' \
    -H "Content-Type: application/json" \
    -X POST \
    -d '{"idToken":"invalid"}' \
    "${BASE_URL}/v1/auth/oauth/${provider}")"

  echo "==> auth/oauth/${provider} (${status})"
  if ! python3 -m json.tool < "${body_file}"; then
    cat "${body_file}"
  fi
  echo
  rm -f "${body_file}"

  case "${status}" in
    400|401)
      ;;
    *)
      echo "Expected a controlled auth failure for ${provider}, got HTTP ${status}" >&2
      exit 1
      ;;
  esac
}

assert_direct_port_closed() {
  local url="$1"
  echo "==> Verifying direct backend port is not publicly reachable"
  if curl -fsS --max-time 10 "${url}" >/dev/null 2>&1; then
    echo "Direct backend port is still publicly reachable at ${url}" >&2
    exit 1
  fi
  echo "Direct backend port is closed to the public."
  echo
}

echo "==> Probing ${BASE_URL}"
fetch_json "healthz" "${BASE_URL}/healthz"
fetch_json "readyz" "${BASE_URL}/readyz"
probe_controlled_auth_failure "google"
probe_controlled_auth_failure "apple"

if [[ -n "${DIRECT_HEALTHCHECK_URL}" ]]; then
  assert_direct_port_closed "${DIRECT_HEALTHCHECK_URL}"
fi

if [[ -n "${AUTH_BEARER_TOKEN}" ]]; then
  fetch_json "auth/me" \
    -H "Authorization: Bearer ${AUTH_BEARER_TOKEN}" \
    "${BASE_URL}/v1/auth/me"

  fetch_json "mobile/bootstrap" \
    -H "Authorization: Bearer ${AUTH_BEARER_TOKEN}" \
    "${BASE_URL}/v1/mobile/bootstrap"

  chat_payload="$(python3 - "${CHAT_PROMPT}" "${CHAT_CAPABILITIES}" <<'PY'
import json
import sys

prompt = sys.argv[1]
capabilities = [item.strip() for item in sys.argv[2].split(",") if item.strip()]
print(json.dumps({
    "source": "mobile",
    "content": prompt,
    "requestedCapabilities": capabilities,
}))
PY
)"

  fetch_json "chat/messages" \
    -H "Authorization: Bearer ${AUTH_BEARER_TOKEN}" \
    -H "Content-Type: application/json" \
    -X POST \
    -d "${chat_payload}" \
    "${BASE_URL}/v1/chat/messages"

  if [[ -n "${DESKTOP_DEVICE_ID}" ]]; then
    task_payload="$(python3 - "${TASK_PROMPT}" "${DESKTOP_DEVICE_ID}" "$(build_capability_json "${TASK_CAPABILITIES}")" <<'PY'
import json
import sys

prompt = sys.argv[1]
device_id = sys.argv[2]
requested_capabilities = json.loads(sys.argv[3])
print(json.dumps({
    "targetDeviceId": device_id,
    "title": "V1 desktop smoke task",
    "payload": {
        "prompt": prompt,
        "source": "mobile",
        "metadata": {
            "smoke": True,
            "releaseTrack": "v1",
        },
    },
    "requestedCapabilities": requested_capabilities,
}))
PY
)"

    fetch_json "tasks" \
      -H "Authorization: Bearer ${AUTH_BEARER_TOKEN}" \
      -H "Content-Type: application/json" \
      -H "Idempotency-Key: v1-smoke-${DESKTOP_DEVICE_ID}" \
      -X POST \
      -d "${task_payload}" \
      "${BASE_URL}/v1/tasks"
  else
    echo "Skipping /v1/tasks probe because DESKTOP_DEVICE_ID is not set."
    echo
  fi
else
  echo "Skipping auth/bootstrap/chat/task probes because AUTH_BEARER_TOKEN is not set."
  echo
fi

if [[ -n "${RUNTIME_BEARER_TOKEN}" ]]; then
  fetch_json "runtime/session" \
    -H "Authorization: Bearer ${RUNTIME_BEARER_TOKEN}" \
    "${BASE_URL}/v1/runtime/session"

  heartbeat_payload='{"status":"online"}'
  fetch_json "runtime/heartbeat" \
    -H "Authorization: Bearer ${RUNTIME_BEARER_TOKEN}" \
    -H "Content-Type: application/json" \
    -X POST \
    -d "${heartbeat_payload}" \
    "${BASE_URL}/v1/runtime/heartbeat"

  fetch_json "runtime/tasks/assigned" \
    -H "Authorization: Bearer ${RUNTIME_BEARER_TOKEN}" \
    "${BASE_URL}/v1/runtime/tasks/assigned"
else
  echo "Skipping runtime probes because RUNTIME_BEARER_TOKEN is not set."
  echo
fi

echo "==> V1 probe completed"
