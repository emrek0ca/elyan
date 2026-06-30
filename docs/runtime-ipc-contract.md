# Elyan Runtime IPC Contract

This document defines the platform-independent JSON IPC contract between the native desktop shell (Swift/Flutter) and the local Python runtime (`bridge.py`).

## Transport Layer
- **Transport**: Standard streams (`stdin` / `stdout`).
- **Format**: Newline-delimited JSON (JSONL). One JSON object per line.
- **Encoding**: UTF-8.
- **Diagnostics**: All `stderr` output is reserved for runtime diagnostics and unstructured logs. It must NOT be parsed as JSON protocol messages.
- **Environment**: The runtime MUST be launched with `PYTHONUNBUFFERED=1`.

## Core Envelopes

Every request sent to the runtime must follow this shape:

```json
{
  "id": "req_12345",
  "taskId": "task_67890",
  "capability": "capability.name",
  "payload": {
    "arg1": "value1"
  }
}
```

Every response returned by the runtime must follow this exact shape:

**Success Response:**
```json
{
  "id": "req_12345",
  "taskId": "task_67890",
  "ok": true,
  "capability": "capability.name",
  "result": {
    "key": "value"
  },
  "events": [],
  "artifacts": [],
  "error": null,
  "durationMs": 150
}
```

**Error Response:**
```json
{
  "id": "req_12345",
  "taskId": "task_67890",
  "ok": false,
  "capability": "capability.name",
  "result": null,
  "events": [],
  "artifacts": [],
  "error": {
    "code": "SAFE_ERROR_CODE",
    "message": "Safe human-readable error message."
  },
  "durationMs": 45
}
```

## Special Capabilities

### `bridge.ready`
When the Python runtime finishes initializing, it immediately emits a success response without a prior request to signal readiness:
```json
{
  "id": "req_xyz",
  "taskId": "req_xyz",
  "ok": true,
  "capability": "bridge.ready",
  "result": {
    "ready": true,
    "startedAt": "2026-06-30T12:00:00Z",
    "pythonVersion": "3.12.3"
  },
  "events": [],
  "artifacts": [],
  "error": null,
  "durationMs": 0
}
```
The Desktop Shell must wait for this message before routing user requests.

### `bootstrap`
The Desktop Shell should call the `bootstrap` capability immediately after `bridge.ready` to hydrate truth from the backend, load workspaces, and sync active conversations.

## Supervisor Responsibilities
- **Asynchronous Launch**: The Desktop Shell must launch the runtime asynchronously and NEVER block the UI thread waiting for `bridge.ready`.
- **Degraded State**: If the Python runtime cannot start (missing Python, missing dependencies, crash), the Desktop Shell must degrade gracefully. It must show a "Runtime Setup Required" or "Degraded" status in the UI, but the app must remain usable for basic settings.
- **Timeouts**: The Desktop Shell must enforce timeouts for requests. If a request times out, it should synthesize an error envelope with `code: "RUNTIME_TIMEOUT"` to resolve internal promises.
- **Process Management**: The Desktop Shell must handle runtime crashes and restart the process with exponential backoff.

## Security & Privacy
- **No Raw Stack Traces**: The runtime catches all unhandled exceptions and normalizes them into safe error codes and generic messages in the `error` envelope.
- **Private Data**: `result`, `events`, and `artifacts` must not leak private credentials, OAuth tokens, or uncontrolled logs.
- **Permissions**: The Desktop Shell owns native OS permissions (Screen Recording, Accessibility). Before passing a request to `desktop_operator` capabilities, it should enforce its own permission gating.
