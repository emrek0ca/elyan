#!/usr/bin/env bash
set -euo pipefail

BASE_URL="${BASE_URL:-https://api.elyan.dev}"
STAMP="${STAMP:-$(date -u +%Y%m%dT%H%M%SZ)}"

need() {
  command -v "$1" >/dev/null 2>&1 || {
    echo "Missing required command: $1" >&2
    exit 1
  }
}

need curl
need python3

TMP_DIR="$(mktemp -d)"
trap 'rm -rf "${TMP_DIR}"' EXIT

request_json() {
  local name="$1"
  local method="$2"
  local path="$3"
  local body_file="${4:-}"
  shift 4 || true
  local extra_args=("$@")
  local response_file="${TMP_DIR}/${name}.json"
  local pretty_file="${TMP_DIR}/${name}.pretty.json"
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

  python3 -m json.tool "${response_file}" > "${pretty_file}"
  echo "==> ${name}" >&2
  cat "${pretty_file}" >&2
  echo >&2
}

json_get() {
  local file="$1"
  local expr="$2"
  python3 - "$file" "$expr" <<'PY'
import json
import sys

with open(sys.argv[1], "r", encoding="utf-8") as handle:
    value = json.load(handle)

for part in sys.argv[2].split("."):
    if isinstance(value, list):
        value = value[int(part)]
    else:
        value = value[part]

if isinstance(value, (dict, list)):
    print(json.dumps(value, ensure_ascii=False))
elif value is None:
    print("")
else:
    print(value)
PY
}

build_body() {
  local file="$1"
  shift
  python3 - "$file" "$@" <<'PY'
import json
import sys

path = sys.argv[1]
payload = json.loads(sys.argv[2])
with open(path, "w", encoding="utf-8") as handle:
    json.dump(payload, handle)
PY
}

write_json() {
  local file="$1"
  local json_payload="$2"
  python3 - "$file" "$json_payload" <<'PY'
import json
import sys

with open(sys.argv[1], "w", encoding="utf-8") as handle:
    json.dump(json.loads(sys.argv[2]), handle)
PY
}

assert_route_case() {
  local name="$1"
  local response_file="$2"
  local selected_desktop_id="${3:-}"
  local expected_target="$4"
  local expected_operational_route="$5"
  local expected_execution_plan="$6"
  local expected_needs_desktop="$7"
  local expected_needs_approval="$8"
  local expected_selected_ignored="$9"
  local expected_user_message="${10:-}"
  local expected_task_target="${11:-}"
  python3 - "$response_file" "${selected_desktop_id}" "${expected_target}" "${expected_operational_route}" "${expected_execution_plan}" "${expected_needs_desktop}" "${expected_needs_approval}" "${expected_selected_ignored}" "${expected_user_message}" "${expected_task_target}" <<'PY'
import json
import sys

response_file = sys.argv[1]
selected_desktop_id = sys.argv[2]
expected_target = sys.argv[3]
expected_operational_route = sys.argv[4]
expected_execution_plan = json.loads(sys.argv[5])
expected_needs_desktop = sys.argv[6] == "true"
expected_needs_approval = sys.argv[7] == "true"
expected_selected_ignored = sys.argv[8] == "true"
expected_user_message = sys.argv[9]
expected_task_target = sys.argv[10]

with open(response_file, "r", encoding="utf-8") as handle:
    data = json.load(handle)

route = data["routeDecision"]
task = data["task"]
task_route = route["taskRoute"]

assert task_route["target"] == expected_target, (task_route["target"], expected_target)
assert task_route["operationalRoute"] == expected_operational_route, (task_route["operationalRoute"], expected_operational_route)
assert task_route["executionPlan"] == expected_execution_plan, (task_route["executionPlan"], expected_execution_plan)
assert task_route["needsDesktop"] is expected_needs_desktop, (task_route["needsDesktop"], expected_needs_desktop)
assert task_route["needsUserApproval"] is expected_needs_approval, (task_route["needsUserApproval"], expected_needs_approval)

message = str(route.get("userFacingMessage") or "")
if expected_user_message:
  assert expected_user_message.lower() in message.lower(), (message, expected_user_message)
else:
  assert "masaüstü" not in message.lower(), message

if expected_selected_ignored == "true":
  assert task["targetDeviceId"] != selected_desktop_id, (task["targetDeviceId"], selected_desktop_id)
else:
  assert task["targetDeviceId"] == expected_task_target, (task["targetDeviceId"], expected_task_target)
PY
  echo "==> ${name} OK"
  echo
}

register_user() {
  local name="$1"
  local email="route-smoke-${name}-${STAMP}@example.com"
  local password="SmokePass!${STAMP#????????T}Aa9"
  local register_file="${TMP_DIR}/${name}-register.json"

  build_body "${register_file}" "$(python3 - "${email}" "${password}" <<'PY'
import json
import sys

print(json.dumps({
    "email": sys.argv[1],
    "password": sys.argv[2],
    "displayName": "Route Smoke User",
}, ensure_ascii=False))
PY
)"
  request_json "${name}-register" POST "/v1/auth/register" "${register_file}"
  local access_token
  access_token="$(json_get "${TMP_DIR}/${name}-register.json" "tokens.accessToken")"

  echo "${access_token}"
}

promote_subscription_to_pro() {
  local user_id="$1"
  node --input-type=module - "${user_id}" <<'NODE'
process.loadEnvFile();
const postgres = (await import('postgres')).default;
const sql = postgres(process.env.DATABASE_URL, { max: 1 });
const userId = process.argv[2];
const now = new Date();
const trialEndsAt = new Date(now.getTime() + 30 * 24 * 60 * 60 * 1000);
try {
  await sql`
    insert into subscriptions (
      user_id,
      plan_code,
      status,
      billing_provider,
      task_limit_monthly,
      ai_credits_monthly,
      current_period_started_at,
      period_ends_at,
      trial_ends_at,
      cancel_at_period_end,
      created_at,
      updated_at
    )
    values (
      ${userId},
      'pro',
      'trialing',
      'welcome_trial',
      2000,
      2000,
      ${now},
      ${trialEndsAt},
      ${trialEndsAt},
      false,
      ${now},
      ${now}
    )
    on conflict (user_id) do update set
      plan_code = excluded.plan_code,
      status = excluded.status,
      billing_provider = excluded.billing_provider,
      task_limit_monthly = excluded.task_limit_monthly,
      ai_credits_monthly = excluded.ai_credits_monthly,
      current_period_started_at = excluded.current_period_started_at,
      period_ends_at = excluded.period_ends_at,
      trial_ends_at = excluded.trial_ends_at,
      cancel_at_period_end = excluded.cancel_at_period_end,
      updated_at = excluded.updated_at
  `;
  console.log('subscription updated');
} finally {
  await sql.end({ timeout: 5 });
}
NODE
}

ensure_desktop_device() {
  local user_id="$1"
  local label="$2"
  node --input-type=module - "${user_id}" "${label}" <<'NODE'
process.loadEnvFile();
const postgres = (await import('postgres')).default;
const sql = postgres(process.env.DATABASE_URL, { max: 1 });
const userId = process.argv[2];
const label = process.argv[3];
const now = new Date();
const capabilities = [
  "filesystem",
  "document_read",
  "document_write",
  "document_parse",
  "image_ocr",
  "file_transform",
  "camera_input",
  "filesystem_read",
  "filesystem_write",
  "app_control",
  "screen_context",
  "terminal",
  "recent_files",
  "browser_control",
  "computer_control",
  "shell_run",
  "summarize",
  "reason",
  "rag",
  "transform_chunks",
  "generate_response",
];
const deviceExternalId = `route-gate-${userId.slice(0, 8)}-${label.toLowerCase().replace(/[^a-z0-9]+/g, "-")}`;
try {
  const existingDevices = await sql`
    select id
    from devices
    where user_id = ${userId}
      and type = 'desktop'
      and external_device_id = ${deviceExternalId}
    limit 1
  `;
  let deviceId = existingDevices[0]?.id ?? null;
  if (!deviceId) {
    const insertedDevices = await sql`
      insert into devices (
        user_id,
        type,
        external_device_id,
        label,
        platform,
        runtime_version,
        app_version,
        is_active,
        paired_at,
        last_seen_at,
        created_at,
        updated_at
      )
      values (
        ${userId},
        'desktop',
        ${deviceExternalId},
        ${label},
        'macos',
        '1.0.0',
        '1.0.0',
        true,
        ${now},
        ${now},
        ${now},
        ${now}
      )
      returning id
    `;
    deviceId = insertedDevices[0].id;
  }

  await sql`
    update runtime_connections
    set
      status = 'online',
      capabilities = ${JSON.stringify(capabilities)}::jsonb,
      capability_states = '{}'::jsonb,
      disconnected_at = null,
      last_heartbeat_at = ${now}
    where device_id = ${deviceId}
  `;

  const runtimeRows = await sql`
    select id
    from runtime_connections
    where device_id = ${deviceId}
      and disconnected_at is null
    order by connected_at desc
    limit 1
  `;
  if (!runtimeRows[0]) {
    await sql`
      insert into runtime_connections (
        device_id,
        user_id,
        status,
        capabilities,
        capability_states,
        connected_at,
        last_heartbeat_at
      )
      values (
        ${deviceId},
        ${userId},
        'online',
        ${JSON.stringify(capabilities)}::jsonb,
        '{}'::jsonb,
        ${now},
        ${now}
      )
    `;
  }

  console.log(deviceId);
} finally {
  await sql.end({ timeout: 5 });
}
NODE
}

send_chat_case() {
  local name="$1"
  local token="$2"
  local prompt="$3"
  local selected_desktop_id="${4:-}"
  local attachment_json="${5:-}"
  local response_name="${name}-chat"
  local body_file="${TMP_DIR}/${response_name}.body.json"
  local request_payload
  if [[ -n "${selected_desktop_id}" ]]; then
    if [[ -n "${attachment_json}" ]]; then
      request_payload="$(python3 - "${prompt}" "${selected_desktop_id}" "${attachment_json}" <<'PY'
import json
import sys

prompt = sys.argv[1]
selected_desktop_id = sys.argv[2]
attachment = json.loads(sys.argv[3])
payload = {
    "source": "mobile",
    "targetDeviceId": selected_desktop_id,
    "content": prompt,
    "requestedCapabilities": [],
    "metadata": {
        "smoke": True,
        "attachment": attachment,
    },
}
print(json.dumps(payload, ensure_ascii=False))
PY
)"
    else
      request_payload="$(python3 - "${prompt}" "${selected_desktop_id}" <<'PY'
import json
import sys

prompt = sys.argv[1]
selected_desktop_id = sys.argv[2]
payload = {
    "source": "mobile",
    "targetDeviceId": selected_desktop_id,
    "content": prompt,
    "requestedCapabilities": [],
    "metadata": {
        "smoke": True,
    },
}
print(json.dumps(payload, ensure_ascii=False))
PY
)"
    fi
  else
    if [[ -n "${attachment_json}" ]]; then
      request_payload="$(python3 - "${prompt}" "${attachment_json}" <<'PY'
import json
import sys

prompt = sys.argv[1]
attachment = json.loads(sys.argv[2])
payload = {
    "source": "mobile",
    "content": prompt,
    "requestedCapabilities": [],
    "metadata": {
        "smoke": True,
        "attachment": attachment,
    },
}
print(json.dumps(payload, ensure_ascii=False))
PY
)"
    else
      request_payload="$(python3 - "${prompt}" <<'PY'
import json
import sys

prompt = sys.argv[1]
payload = {
    "source": "mobile",
    "content": prompt,
    "requestedCapabilities": [],
    "metadata": {
        "smoke": True,
    },
}
print(json.dumps(payload, ensure_ascii=False))
PY
)"
    fi
  fi

  printf '%s' "${request_payload}" > "${body_file}"
  request_json "${response_name}" POST "/v1/chat/messages" "${body_file}" -H "Authorization: Bearer ${token}"
}

echo "==> Route gate smoke against ${BASE_URL}"

primary_token="$(register_user "primary")"
primary_user_id="$(json_get "${TMP_DIR}/primary-register.json" "user.id")"
promote_subscription_to_pro "${primary_user_id}"
primary_desktop_id="$(ensure_desktop_device "${primary_user_id}" "Route Gate Primary Desktop")"

attachment_shared='{"name":"ozetlenecek-belge.pdf","contentType":"application/pdf","text":"Belge içeriği"}'
attachment_pdf='{"name":"important-matter.pdf","contentType":"application/pdf","text":"PDF metni"}'

send_chat_case "case-1" "${primary_token}" "şu belgeyi özetle" "${primary_desktop_id}" "${attachment_shared}"
request_file="${TMP_DIR}/case-1-chat.json"
python3 - "${request_file}" "${primary_desktop_id}" <<'PY'
import json
import sys

with open(sys.argv[1], "r", encoding="utf-8") as handle:
    data = json.load(handle)

route = data["routeDecision"]
task = data["task"]
assert route["taskRoute"]["needsDesktop"] is False
assert route["taskRoute"]["operationalRoute"] == "server_brain"
assert route["taskRoute"]["executionPlan"] == ["mobile_local", "server_brain"]
assert route["taskRoute"]["target"] == "hybrid"
assert task["targetDeviceId"] != sys.argv[2]
assert "masaüstü" not in str(route.get("userFacingMessage") or "").lower()
PY
echo "==> case-1 OK"
echo

send_chat_case "case-2" "${primary_token}" "bu PDF’ten önemli maddeleri çıkar" "" "${attachment_pdf}"
request_file="${TMP_DIR}/case-2-chat.json"
python3 - "${request_file}" <<'PY'
import json
import sys

with open(sys.argv[1], "r", encoding="utf-8") as handle:
    data = json.load(handle)

route = data["routeDecision"]
task = data["task"]
assert route["taskRoute"]["needsDesktop"] is False
assert route["taskRoute"]["operationalRoute"] == "server_brain"
assert route["taskRoute"]["executionPlan"] == ["mobile_local", "server_brain"]
assert route["taskRoute"]["target"] == "hybrid"
assert task["targetDeviceId"]
assert "masaüstü" not in str(route.get("userFacingMessage") or "").lower()
PY
echo "==> case-2 OK"
echo

send_chat_case "case-4" "${primary_token}" "bu fotoyu masaüstüne kaydet" "${primary_desktop_id}"
request_file="${TMP_DIR}/case-4-chat.json"
python3 - "${request_file}" "${primary_desktop_id}" <<'PY'
import json
import sys

with open(sys.argv[1], "r", encoding="utf-8") as handle:
    data = json.load(handle)

route = data["routeDecision"]
task = data["task"]
assert route["taskRoute"]["needsDesktop"] is True
assert route["taskRoute"]["operationalRoute"] == "desktop_runtime"
assert route["taskRoute"]["executionPlan"] == ["mobile_local", "desktop_runtime"]
assert route["taskRoute"]["needsUserApproval"] is False
assert route["taskRoute"]["target"] == "hybrid"
assert task["targetDeviceId"] == sys.argv[2]
PY
echo "==> case-4 OK"
echo

send_chat_case "case-5" "${primary_token}" "Bugün ne çalışmalıyım?" "${primary_desktop_id}"
request_file="${TMP_DIR}/case-5-chat.json"
python3 - "${request_file}" "${primary_desktop_id}" <<'PY'
import json
import sys

with open(sys.argv[1], "r", encoding="utf-8") as handle:
    data = json.load(handle)

route = data["routeDecision"]
task = data["task"]
assert route["taskRoute"]["needsDesktop"] is False
assert route["taskRoute"]["operationalRoute"] == "server_brain"
assert route["taskRoute"]["executionPlan"] == ["server_brain"]
assert route["taskRoute"]["target"] == "server_brain"
assert task["targetDeviceId"] != sys.argv[2]
assert "masaüstü" not in str(route.get("userFacingMessage") or "").lower()
PY
echo "==> case-5 OK"
echo

secondary_token="$(register_user "secondary")"
secondary_user_id="$(json_get "${TMP_DIR}/secondary-register.json" "user.id")"
promote_subscription_to_pro "${secondary_user_id}"
secondary_desktop_id="$(ensure_desktop_device "${secondary_user_id}" "Route Gate Secondary Desktop")"
send_chat_case "case-3-unavailable" "${secondary_token}" "bilgisayarımda son çalıştığımız belgeyi özetle" "${secondary_desktop_id}"
request_file="${TMP_DIR}/case-3-unavailable-chat.json"
python3 - "${request_file}" <<'PY'
import json
import sys

with open(sys.argv[1], "r", encoding="utf-8") as handle:
    data = json.load(handle)

route = data["routeDecision"]
assert route["taskRoute"]["needsDesktop"] is True
assert route["taskRoute"]["executionPlan"] == ["desktop_runtime", "server_brain"]
assert route["taskRoute"]["operationalRoute"] == "desktop_runtime"
assert route["route"] != "server_brain"
message = str(route.get("userFacingMessage") or "")
assert "masaüstü" in message.lower(), message
PY
echo "==> case-3-unavailable OK"
echo

echo "==> Route gate smoke completed"
