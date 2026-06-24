#!/usr/bin/env bash
set -euo pipefail

BASE_URL="${BASE_URL:-https://api.elyan.dev}"
DIRECT_HEALTHCHECK_URL="${DIRECT_HEALTHCHECK_URL:-http://84.247.172.213:4000/healthz}"
EVIDENCE_ROOT="${EVIDENCE_ROOT:-docs/release/evidence}"
STAMP="${STAMP:-$(date -u +%Y%m%dT%H%M%SZ)}"
EVIDENCE_DIR="${EVIDENCE_ROOT}/${STAMP}-vps-core-smoke"
DESKTOP_CAPABILITIES="${DESKTOP_CAPABILITIES:-runtime.status,browser.control,document.read}"
CHAT_PROMPT="${CHAT_PROMPT:-V1 public chat smoke check. Reply with a short acknowledgement.}"
TASK_PROMPT="${TASK_PROMPT:-Open the browser capability smoke path and return a short acknowledgement.}"

need() {
  command -v "$1" >/dev/null 2>&1 || {
    echo "Missing required command: $1" >&2
    exit 1
  }
}

need curl
need python3
need mktemp

mkdir -p "${EVIDENCE_DIR}"

TMP_DIR="$(mktemp -d)"
trap 'rm -rf "${TMP_DIR}"' EXIT

json_get() {
  local file="$1"
  local expr="$2"
  python3 - "$file" "$expr" <<'PY'
import json
import sys

data = json.load(open(sys.argv[1], "r", encoding="utf-8"))
value = data
for part in sys.argv[2].split("."):
    if isinstance(value, list):
        value = value[int(part)]
    else:
        value = value[part]
if isinstance(value, (dict, list)):
    print(json.dumps(value))
elif value is None:
    print("")
else:
    print(value)
PY
}

json_pretty_to() {
  local src="$1"
  local dest="$2"
  python3 -m json.tool "${src}" >"${dest}"
}

request_json() {
  local name="$1"
  local method="$2"
  local path="$3"
  local body_file="${4:-}"
  shift 4 || true
  local extra_args=("$@")
  local response_file="${EVIDENCE_DIR}/${name}.json"
  local pretty_file="${EVIDENCE_DIR}/${name}.pretty.json"
  local curl_args=(-sS -X "${method}" -o "${response_file}" -w "%{http_code}")

  if [[ -n "${body_file}" ]]; then
    curl_args+=(-H "Content-Type: application/json" -d @"${body_file}")
  fi
  if ((${#extra_args[@]})); then
    curl_args+=("${extra_args[@]}")
  fi
  curl_args+=("${BASE_URL}${path}")
  local status
  status="$(curl "${curl_args[@]}")"
  if [[ "${status}" -lt 200 || "${status}" -ge 300 ]]; then
    echo "Request ${name} failed with HTTP ${status}" >&2
    cat "${response_file}" >&2
    exit 1
  fi

  json_pretty_to "${response_file}" "${pretty_file}"
}

assert_direct_port_closed() {
  local output_file="${EVIDENCE_DIR}/direct-port-4000.txt"
  if curl -sS --max-time 10 "${DIRECT_HEALTHCHECK_URL}" >"${output_file}" 2>&1; then
    echo "Direct backend port is still publicly reachable: ${DIRECT_HEALTHCHECK_URL}" >&2
    exit 1
  fi
}

request_json "healthz" GET "/healthz" ""
request_json "readyz" GET "/readyz" ""
assert_direct_port_closed

email="v1-smoke-${STAMP}@example.com"
password="SmokePass!${STAMP#????????T}Aa9"

register_body="${TMP_DIR}/auth-register.json"
python3 - "${register_body}" "${email}" "${password}" <<'PY'
import json
import sys

with open(sys.argv[1], "w", encoding="utf-8") as handle:
    json.dump({
        "email": sys.argv[2],
        "password": sys.argv[3],
        "displayName": "V1 Smoke User",
    }, handle)
PY
request_json "auth-register" POST "/v1/auth/register" "${register_body}"
auth_token="$(json_get "${EVIDENCE_DIR}/auth-register.json" "tokens.accessToken")"

request_json "auth-me" GET "/v1/auth/me" "" -H "Authorization: Bearer ${auth_token}"

mobile_body="${TMP_DIR}/mobile-register.json"
python3 - "${mobile_body}" "${STAMP}" <<'PY'
import json
import sys

stamp = sys.argv[2]
with open(sys.argv[1], "w", encoding="utf-8") as handle:
    json.dump({
        "externalDeviceId": f"v1-smoke-mobile-{stamp}",
        "label": "V1 Smoke iPhone",
        "platform": "ios",
        "appVersion": "1.0.0",
    }, handle)
PY
request_json "mobile-register" POST "/v1/devices/mobile/register" "${mobile_body}" -H "Authorization: Bearer ${auth_token}"
request_json "mobile-bootstrap" GET "/v1/mobile/bootstrap" "" -H "Authorization: Bearer ${auth_token}"

realtime_stream_file="${EVIDENCE_DIR}/realtime-stream.txt"
curl -sS -H "Authorization: Bearer ${auth_token}" --max-time 10 --no-buffer "${BASE_URL}/v1/realtime/stream" >"${realtime_stream_file}" 2>&1 || true
if ! grep -q 'event: ready' "${EVIDENCE_DIR}/realtime-stream.txt"; then
  echo "Realtime stream did not emit event: ready" >&2
  cat "${EVIDENCE_DIR}/realtime-stream.txt" >&2
  exit 1
fi

pair_create_body="${TMP_DIR}/pair-create.json"
python3 - "${pair_create_body}" "${STAMP}" <<'PY'
import json
import sys

stamp = sys.argv[2]
with open(sys.argv[1], "w", encoding="utf-8") as handle:
    json.dump({
        "deviceLabel": "V1 Smoke Desktop",
        "platform": "macos",
        "runtimeVersion": "1.0.0",
        "externalDeviceId": f"v1-smoke-desktop-{stamp}",
    }, handle)
PY
request_json "pairing-create" POST "/v1/pairing/sessions" "${pair_create_body}" -H "Authorization: Bearer ${auth_token}"

pair_session_id="$(json_get "${EVIDENCE_DIR}/pairing-create.json" "sessionId")"
pairing_code="$(json_get "${EVIDENCE_DIR}/pairing-create.json" "pairingCode")"
pairing_token="$(json_get "${EVIDENCE_DIR}/pairing-create.json" "pairingToken")"
desktop_device_id="$(json_get "${EVIDENCE_DIR}/pairing-create.json" "desktopDevice.id")"

pair_claim_body="${TMP_DIR}/pair-claim.json"
python3 - "${pair_claim_body}" "${pairing_code}" <<'PY'
import json
import sys

with open(sys.argv[1], "w", encoding="utf-8") as handle:
    json.dump({
        "pairingCode": sys.argv[2],
        "mobileDevice": {
            "label": "V1 Smoke iPhone",
            "platform": "ios",
            "appVersion": "1.0.0",
        },
    }, handle)
PY
request_json "pairing-claim" POST "/v1/pairing/sessions/${pair_session_id}/claim" "${pair_claim_body}" -H "Authorization: Bearer ${auth_token}"
request_json "pairing-status" GET "/v1/pairing/sessions/${pair_session_id}" "" -H "x-pairing-token: ${pairing_token}"

runtime_device_id="$(json_get "${EVIDENCE_DIR}/pairing-status.json" "runtimeAuth.deviceId")"
runtime_device_secret="$(json_get "${EVIDENCE_DIR}/pairing-status.json" "runtimeAuth.deviceSecret")"

runtime_register_body="${TMP_DIR}/runtime-register.json"
python3 - "${runtime_register_body}" "${runtime_device_id}" "${runtime_device_secret}" "${DESKTOP_CAPABILITIES}" <<'PY'
import json
import sys

capabilities = [item.strip() for item in sys.argv[4].split(",") if item.strip()]
with open(sys.argv[1], "w", encoding="utf-8") as handle:
    json.dump({
        "deviceId": sys.argv[2],
        "deviceSecret": sys.argv[3],
        "runtimeVersion": "1.0.0",
        "capabilities": capabilities,
        "capabilityStates": {
            "browser.control": {"available": True},
            "document.read": {"available": True},
            "runtime.status": {"available": True},
        },
    }, handle)
PY
request_json "runtime-register" POST "/v1/runtime/register" "${runtime_register_body}"
runtime_token="$(json_get "${EVIDENCE_DIR}/runtime-register.json" "tokens.accessToken")"

runtime_heartbeat_body="${TMP_DIR}/runtime-heartbeat.json"
python3 - "${runtime_heartbeat_body}" "${DESKTOP_CAPABILITIES}" <<'PY'
import json
import sys

capabilities = [item.strip() for item in sys.argv[2].split(",") if item.strip()]
with open(sys.argv[1], "w", encoding="utf-8") as handle:
    json.dump({
        "status": "online",
        "capabilities": capabilities,
        "capabilityStates": {
            "browser.control": {"available": True},
            "document.read": {"available": True},
            "runtime.status": {"available": True},
        },
    }, handle)
PY
request_json "runtime-heartbeat" POST "/v1/runtime/heartbeat" "${runtime_heartbeat_body}" -H "Authorization: Bearer ${runtime_token}"
request_json "runtime-session" GET "/v1/runtime/session" "" -H "Authorization: Bearer ${runtime_token}"

chat_body="${TMP_DIR}/chat-message.json"
python3 - "${chat_body}" "${CHAT_PROMPT}" <<'PY'
import json
import sys

with open(sys.argv[1], "w", encoding="utf-8") as handle:
    json.dump({
        "source": "mobile",
        "content": sys.argv[2],
        "requestedCapabilities": [],
        "metadata": {
            "smoke": True,
            "releaseTrack": "v1",
        },
    }, handle)
PY
request_json "chat-message" POST "/v1/chat/messages" "${chat_body}" -H "Authorization: Bearer ${auth_token}"

task_body="${TMP_DIR}/task-create.json"
python3 - "${task_body}" "${desktop_device_id}" "${TASK_PROMPT}" <<'PY'
import json
import sys

with open(sys.argv[1], "w", encoding="utf-8") as handle:
    json.dump({
        "targetDeviceId": sys.argv[2],
        "title": "V1 Desktop Smoke Task",
        "payload": {
            "prompt": sys.argv[3],
            "source": "mobile",
            "metadata": {
                "smoke": True,
                "releaseTrack": "v1",
            },
        },
        "requestedCapabilities": [
            "browser.control",
            "document.read",
        ],
    }, handle)
PY
request_json "task-create" POST "/v1/tasks" "${task_body}" -H "Authorization: Bearer ${auth_token}" -H "Idempotency-Key: v1-vps-smoke-${STAMP}"
request_json "runtime-tasks-assigned" GET "/v1/runtime/tasks/assigned" "" -H "Authorization: Bearer ${runtime_token}"

task_id="$(json_get "${EVIDENCE_DIR}/task-create.json" "task.id")"
if ! grep -q "${task_id}" "${EVIDENCE_DIR}/runtime-tasks-assigned.json"; then
  echo "Assigned runtime task list does not contain created task ${task_id}" >&2
  exit 1
fi

summary_file="${EVIDENCE_DIR}/SUMMARY.md"
cat >"${summary_file}" <<EOF
# Elyan V1 VPS Core Smoke Evidence

- Timestamp (UTC): ${STAMP}
- Base URL: ${BASE_URL}
- Direct backend port check: expected closed at \`${DIRECT_HEALTHCHECK_URL}\`
- Pairing session: \`${pair_session_id}\`
- Desktop device: \`${desktop_device_id}\`
- Runtime device: \`${runtime_device_id}\`
- Created task: \`${task_id}\`

## Verified chain

- \`GET /healthz\`
- \`GET /readyz\`
- direct \`:4000\` public path closed
- \`POST /v1/auth/register\`
- \`GET /v1/auth/me\`
- \`POST /v1/devices/mobile/register\`
- \`GET /v1/mobile/bootstrap\`
- \`GET /v1/realtime/stream\` emitted \`event: ready\`
- \`POST /v1/pairing/sessions\`
- \`POST /v1/pairing/sessions/:sessionId/claim\`
- \`GET /v1/pairing/sessions/:sessionId\`
- \`POST /v1/runtime/register\`
- \`POST /v1/runtime/heartbeat\`
- \`GET /v1/runtime/session\`
- \`POST /v1/chat/messages\`
- \`POST /v1/tasks\`
- \`GET /v1/runtime/tasks/assigned\`

## External blockers kept explicit

- \`APPLE_APP_STORE_*\`
- \`GOOGLE_PLAY_*\`
- \`IYZICO_*\`

Server core smoke is green. Commercial readiness remains externally blocked.
EOF

python3 - "${EVIDENCE_DIR}" <<'PY'
import json
import pathlib
import sys

evidence_dir = pathlib.Path(sys.argv[1])
sensitive_suffixes = {"auth-register.json", "runtime-register.json", "pairing-status.json"}
redactions = {
    ("auth-register.json", "tokens", "accessToken"): "[redacted]",
    ("auth-register.json", "tokens", "refreshToken"): "[redacted]",
    ("runtime-register.json", "tokens", "accessToken"): "[redacted]",
    ("pairing-create.json", "pairingToken"): "[redacted]",
    ("pairing-create.json", "pairingCode"): "[redacted]",
    ("pairing-status.json", "runtimeAuth", "deviceSecret"): "[redacted]",
}

for json_path in evidence_dir.glob("*.json"):
    with json_path.open("r", encoding="utf-8") as handle:
        payload = json.load(handle)
    for (filename, *path), replacement in redactions.items():
        if json_path.name != filename:
            continue
        target = payload
        for part in path[:-1]:
            target = target.get(part, {})
        if isinstance(target, dict) and path[-1] in target:
            target[path[-1]] = replacement
    with json_path.open("w", encoding="utf-8") as handle:
        json.dump(payload, handle, indent=2)
        handle.write("\n")
PY

echo "Smoke evidence captured in ${EVIDENCE_DIR}"
