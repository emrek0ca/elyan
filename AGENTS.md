# Elyan Engineering Guide

You are working on Elyan.

Elyan is a production-grade local-first AI agent system that can think, plan, execute, verify, learn, and improve over time.

## Core architecture

### 1. Elyan Desktop
- Shipping desktop shell: `electron/`
- Cross-platform target: macOS, Windows, Linux
- UI stack: Electron renderer/preload/main
- Execution core: Python runtime in `runtime/`
- Native support: C++ thin OS shim and Rust sidecars where needed
- Private/local work stays on device
- Desktop must start asynchronously and fail safely when runtime or native dependencies are missing
- UI must never freeze because of runtime or native work

### 2. Elyan Backend / Control-plane
- Handles auth, billing, devices, pairing, routing, realtime, quota, learning events, retrieval metadata, and orchestration truth
- Does not execute private local computer actions directly
- Does not receive private local context unless the product flow explicitly allows it

### 3. Elyan Mobile
- Mobile app remains Flutter-only in `/Users/emrekoca/Desktop/mobile-elyan`
- Targets iOS and Android only
- Sends tasks, shows status/results, and pairs with desktop
- Renders backend truth and does not talk directly to local desktop engines outside the Elyan task flow

## Required execution boundary

Desktop UI  
-> preload API  
-> Electron main  
-> Python runtime bridge  
-> capability registry  
-> safety policy  
-> adapter  
-> library / tool / native integration  
-> structured result

Never use:
- renderer -> Node/native libraries directly
- mobile -> local engine directly
- backend -> private local computer tools directly

## Native rules

- Prefer Python as the execution orchestrator.
- Use C++ only as a thin OS integration layer for Electron main:
  - window/system integration
  - process/app discovery
  - permission probes
  - safe OS capability truth
- Use Rust for compute-heavy native sidecars such as local indexing.
- Do not move business logic into the C++ addon.
- All native features must degrade safely when unavailable.

## Engineering rules

- Do not redesign Elyan into a separate architecture.
- Improve the current Electron + Python + native structure only.
- Keep changes minimal, isolated, and production-grade.
- Every capability must go through registry + adapter + safety policy.
- Missing dependencies must not crash the desktop app.
- Heavy modules must lazy-load.
- Long-running operations must support timeout/cancel.
- No uncontrolled polling.
- No raw stack traces to users.
- No private user input in logs by default.
- No hardcoded user-specific paths in production code.

## Desktop direction

- Flutter desktop is no longer part of the shipping product path.
- Do not add new desktop work in Flutter.
- New desktop UI, native, runtime, and packaging work belongs under:
  - `electron/`
  - `runtime/`
  - `native/`

## Success shape

All runtime calls must use structured JSON-compatible request/response envelopes.

Success:

```json
{
  "id": "req_123",
  "taskId": "task_123",
  "ok": true,
  "capability": "capability.name",
  "result": {},
  "events": [],
  "artifacts": [],
  "error": null,
  "durationMs": 0
}
```

Error:

```json
{
  "id": "req_123",
  "taskId": "task_123",
  "ok": false,
  "capability": "capability.name",
  "result": null,
  "events": [],
  "artifacts": [],
  "error": {
    "code": "SAFE_ERROR_CODE",
    "message": "Safe human-readable error"
  },
  "durationMs": 0
}
```
