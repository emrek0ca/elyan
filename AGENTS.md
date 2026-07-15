# Elyan V1 Engineering Roadmap

You are working on Elyan. Elyan is not a chatbot; it is a production-grade, local-first AI agent system that can think, plan, execute, verify, learn, and improve over time.

This file is the single engineering direction document for the desktop repo. When another session reads only this file, it should understand the current architecture, what is already in place, and what must be completed before V1 is ready to ship.

## Current Product Shape

- Desktop app lives at the repository root and is the shipping desktop product.
- Desktop stack: GUI YOK — tek Python motoru. `cli/` (kurulum + eşleştirme + daemon yönetimi), `runtime/` (başsız daemon + pystray tepsi ikonu). Swift yalnız `helpers/` altında başsız macOS izin köprüsü olarak yaşar (takvim/ekran/operator).
- Mobile remains Flutter-only in `/Users/emrekoca/Desktop/mobile-elyan` for iOS and Android.
- Backend/control-plane remains separate in `/Users/emrekoca/Desktop/elyan-backend`.

## System Boundary

Required desktop execution path:

`SwiftUI (macOS) / Flutter (Windows) -> JSON stdin/stdout IPC -> Python runtime bridge -> capability registry -> safety policy -> adapter -> library/tool/native integration -> structured result`

Never use:

- renderer -> Node/native libraries directly
- mobile -> local engine directly
- backend -> private local computer tools directly
- UI/business logic -> third-party library calls scattered across components

Mobile sends tasks and shows status/results. Backend owns auth, billing, devices, pairing, routing, quota, realtime, learning events, retrieval metadata, and orchestration truth. Desktop owns private/local execution and full computer control after permission/safety checks.

## What Exists Now

- Native macOS SwiftUI desktop shell with RuntimeBridgeSwift, PythonRuntimeSupervisor, and Liquid Glass design system.
- Python runtime bridge with structured request/response envelopes, backend truth refresh, auth/login/register/logout, pairing, runtime registration/heartbeat/session, conversation/session actions, task relay, MCP, skills, local model status, executor core, and capability registry.
- Runtime task flow includes backend-mediated assigned tasks, dispatch ack, status/artifact reporting, approval resume/cancel paths, and local task inbox state.
- Capability categories already include desktop operator, browser, document read/write, OCR, image read/generation, media, speech, math, LaTeX, retrieval, local models, MCP tools, skills, shell, calendar/reminders, email, data analysis, charting, and quantum actions.
- Desktop parity aligns with the mobile product flow: signed-in home chat, session-based history/archive, backend truth hydration, runtime/device readiness, active remote task inbox, approval-required tasks, reconnect/degraded/offline states, and desktop-only power surfaces for apps/skills/operator readiness.
- Mobile design/behavior remains the reference for chat, auth, history, pairing, realtime, and task status.

## Runtime Envelope Contract

Every runtime call must be JSON-compatible and return a safe envelope.

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

No raw stack traces, private prompt/file contents, credentials, or uncontrolled logs should surface to users by default.

## Engineering Rules

- Improve the existing Electron + Python + native architecture only.
- Keep changes minimal, isolated, testable, and production-grade.
- Every capability goes through registry + adapter + safety policy.
- Missing dependencies must degrade safely and must not crash app startup.
- Heavy modules must lazy-load. Startup should load only protocol/config/registry/health truth.
- Runtime startup must be asynchronous. Desktop UI must never freeze because Python, native modules, MCP, OCR, Playwright, local models, or document conversion are slow/missing.
- Long-running work must support timeout and cancellation where feasible.
- No uncontrolled polling, infinite loops, or hidden background actions.
- No hardcoded user-specific paths. Use `pathlib` in Python and platform-safe APIs in TypeScript/Dart.
- No `shell=True` unless documented and unavoidable. Prefer direct process arguments.
- Preserve macOS, Windows, and Linux behavior.
- Preserve current UI/UX unless a UI change is explicitly part of the task.

## Safety Policy

Blocked by default:

- arbitrary shell commands
- file deletion/overwrite
- private folder scanning without permission
- system settings changes
- credential access
- email/message sending
- payments/billing
- destructive browser/computer actions
- uncontrolled clicking/typing
- hidden automation
- background side effects without taskId/traceId

Permission required:

- browser control
- computer screenshot/click/type/hotkey
- file write
- document edit/export
- automation creation
- MCP tool call with side effects
- external API action
- connector write action

Allowed initially:

- runtime status
- capability listing
- text processing
- safe document parsing
- safe math/LaTeX conversion
- safe read-only operations in allowed workspace
- local model/dependency status checks

## Dependency Direction

`requirements.txt` is a runtime dependency manifest and should remain as a build/install input. Keep AGENTS as the guidance document; do not delete dependency manifests required by packaging or local setup.

Current Python dependency families include:

- runtime/API: `requests`, `httpx`, `websocket-client`
- agent/model routing: `google-genai`, `litellm`, `langgraph`
- document/OCR/data: `markitdown`, `pymupdf`, `python-docx`, `openpyxl`, `python-pptx`, `pandas`, `matplotlib`
- speech/media/vision: `SpeechRecognition`, `pyaudio`, `faster-whisper`, `sounddevice`, `soundfile`, `Pillow`, `playwright`
- math/quantum: `sympy`, `latex2sympy2_extended`, `qiskit`, `qiskit-aer`
- system/MCP: `psutil`, `mcp`

Do not add unused dependencies. Prefer one primary stable library per capability and one fallback only when there is a concrete failure mode.

## V1 Done Point

V1 is ready only when all of these are true:

- Desktop boots asynchronously on macOS, Windows, and Linux, and degrades safely when Python/runtime/native dependencies are missing.
- Login/register/logout, backend truth refresh, pairing, runtime registration, heartbeat/session, and assigned task execution work through the runtime bridge.
- Mobile -> backend -> desktop task flow is preserved. No direct mobile-to-engine shortcut exists.
- Session history remains chat/session-based, not raw task-row based.
- Desktop task shell shows runtime/device readiness, task inbox, approval-required tasks, reconnect/degraded/offline states, and desktop-only power surfaces.
- Permission-gated desktop capabilities fail closed with clear human messages and no raw stack traces.
- MCP and skills are optional; runtime boots without them, discovers dynamically, times out safely, and normalizes tool results.
- Local private execution stays on desktop unless the product flow explicitly allows sharing.
- Packaging works with optional PyInstaller runtime bundle and fallback/degraded runtime status.
- Verification passes:
  - `python -m pytest tests/test_runtime_startup_contract.py tests/test_runtime_bridge_contract.py -q`

## Commands

Masaüstünde GUI YOKTUR: ürün CLI + başsız daemon + pystray tepsi ikonudur.
Swift/Xcode hedefi kaldırıldı; `helpers/` altındaki Swift kaynakları GUI değil,
başsız yeteneklerin (takvim/ekran/operator) macOS izin köprüleridir — kalır.

Run the desktop runtime locally:

```bash
python -m cli.main run     # ön planda (hata ayıklama); arka plan için: start
```

Full verification:

```bash
python -m pytest tests/ -q
```

## Roadmap Discipline

When adding a capability:

1. Inspect the current extension point first.
2. Choose the smallest stable library already allowed by the dependency direction.
3. Add it through adapter + registry + safety policy.
4. Keep UI changes minimal and presentation-only.
5. Add dependency checks and graceful failure.
6. Add tests/manual verification.
7. Report exact files changed.

If a task risks changing backend/mobile boundaries, stop and preserve this invariant:

`Mobile -> Backend/control-plane -> Desktop runtime`

Desktop can control the whole computer only through explicit, permission-gated, task-scoped runtime capabilities.
