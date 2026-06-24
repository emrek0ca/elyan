# Mobile Frontend Integration Contract

This document is the backend truth for Elyan's server control-plane.

The server owns:

- user auth and sessions
- subscription and account truth
- mobile and desktop device records
- desktop pairing and runtime registration
- task relay state
- realtime task updates for mobile

The desktop product owns:

- execution of real work
- LLM/provider selection
- MCP setup
- skills and automations
- local runtime UX

## Base Rules

- Same-machine simulator base URL: `http://127.0.0.1:4000`
- Physical mobile devices and other machines must use the backend machine LAN IP or public host, for example `http://192.168.1.15:4000`
- Never point mobile or desktop clients on another device to `127.0.0.1` or `localhost`; those only resolve to that client's own machine
- User auth header: `Authorization: Bearer <accessToken>`
- Runtime auth header is only for the desktop runtime
- Every response includes `x-request-id` for trace correlation
- Mobile consumes SSE from `/v1/realtime/stream`
- Desktop runtime uses HTTP plus websocket at `/v1/realtime/runtime`

## Required Env

- `APP_BASE_URL` must be the backend origin reachable by the client device
- Copy `.env.example` to `.env` before booting the service
- Recommended shared dev boot path: `docker compose up --build`
- In the compose stack, backend reaches Postgres through `postgres:5432`; do not hardcode another developer's local database username into shared setup instructions

## 1. User Auth

- `POST /v1/auth/register`
- `POST /v1/auth/login`
- `POST /v1/auth/refresh`
- `GET /v1/auth/me`

`/me` returns:

```json
{
  "user": {
    "id": "uuid",
    "email": "user@example.com",
    "displayName": "Elyan User",
    "createdAt": "iso-date"
  },
  "subscription": {
    "planCode": "free",
    "status": "free",
    "tokensMonthly": 0,
    "taskLimitMonthly": 25,
    "periodEndsAt": "2026-07-13T09:00:00.000Z",
    "trialEndsAt": "2026-07-13T09:00:00.000Z",
    "tokenBalance": 0,
    "tokensGrantedThisPeriod": 0,
    "tokenPeriodEndsAt": "2026-07-13T09:00:00.000Z",
    "tokenStatus": "trial",
    "trialOffer": {
      "code": "welcome_pro_30d",
      "planCode": "pro",
      "durationDays": 30,
      "status": "available",
      "eligible": true,
      "claimed": false,
      "claimPath": "/v1/billing/trials/pro/claim",
      "expiresAt": "2026-07-13T09:00:00.000Z"
    }
  },
  "metrics": {
    "desktopCount": 1
  },
  "usage": {
    "tasksUsed": 0,
    "tasksRemaining": 25,
    "tokensUsed": 0,
    "tokensRemaining": 0,
    "tokenBalance": 0,
    "tokensGrantedThisPeriod": 0,
    "tokenPeriodEndsAt": "2026-07-13T09:00:00.000Z",
    "promptTokens": 0,
    "completionTokens": 0,
    "totalTokens": 0
  },
  "brain": {
    "chat": {
      "homeSurface": "chat"
    }
  }
}
```

`subscription` is the stable plan-truth shape. Mobile should treat `planCode`, `status`, `tokensMonthly`, `taskLimitMonthly`, `brainProfile`, `periodEndsAt`, `tokenBalance`, and `tokenPeriodEndsAt` as the guaranteed fields for active plan state.
`subscription.trialOffer` is additive trial-claim truth for the first-account welcome modal. If `trialOffer.status == "available"` and `trialOffer.eligible == true`, the frontend may show the welcome modal and call `trialOffer.claimPath`. Do not activate Pro locally; wait for the backend response.
`usage` is the stable usage-truth shape for task and token counters. Mobile should not derive token usage from local chat history or provider-side estimates.
User-facing labels must say `Token` only. Do not show `kredi`, `credit`, or `kota` in mobile or desktop UI. Legacy response fields named `aiCredits*` and `credit*` may still exist for backward compatibility, but new frontend code must ignore them and read the `tokens*` / `token*` fields.
`brain.chat.homeSurface` is the signed-in landing truth. Mobile should treat it as the authoritative default surface when the app boots or restores a session.

### Token Management Rules

- Backend token units are plan allowance units, not raw provider prompt tokens.
- Chat and task work are metered differently by the backend. Public chat is lighter; server-brain task/plan work is heavier but bounded.
- Short chat such as greetings should normally debit `1` token unit.
- Longer or deeper prompts, planning workload, research context, and longer model answers can debit more than `1` token unit.
- Fixed Elyan system prompt, constitution text, and backend orchestration context are heavily discounted and must not drain the user's token allowance by themselves.
- Desktop/local-runtime work consumes task allowance server-side but does not consume server-brain token units unless the backend actually invokes the shared brain.
- Frontend must never estimate or decrement tokens locally from message character count. Always use backend-returned `usage`.

### Welcome Pro Trial Claim

- `POST /v1/billing/trials/pro/claim`
- Requires `Authorization: Bearer <accessToken>`
- Body: none
- Response:

```json
{
  "billing": {
    "subscription": {
      "planCode": "pro",
      "status": "trialing",
      "tokensMonthly": 2000,
      "taskLimitMonthly": 2000,
      "tokenBalance": 2000,
      "tokensGrantedThisPeriod": 2000,
      "tokenPeriodEndsAt": "2026-07-13T09:02:11.000Z",
      "tokenStatus": "available",
      "trialEndsAt": "2026-07-13T09:02:11.000Z",
      "trialOffer": {
        "code": "welcome_pro_30d",
        "planCode": "pro",
        "durationDays": 30,
        "status": "claimed",
        "eligible": false,
        "claimed": true,
        "claimPath": "/v1/billing/trials/pro/claim",
        "expiresAt": "2026-07-13T09:02:11.000Z"
      }
    }
  }
}
```

Frontend note: show the first-account welcome modal only from backend truth. Use `subscription.trialOffer.status == "available"` for the claim button. After a successful claim, refresh `/v1/auth/me` or `/v1/mobile/bootstrap` and render the returned `pro/trialing` plan plus `brainProfile.tier == "premium"`. If the endpoint returns `409`, hide the claim button and refresh backend truth.

## 2. Mobile Device Registration

- `POST /v1/devices/mobile/register`
- `GET /v1/devices`
- `GET /v1/devices/:deviceId/backlog`
- `POST /v1/devices/:deviceId/deactivate`

Register body:

```json
{
  "externalDeviceId": "ios-device-id",
  "label": "User iPhone",
  "platform": "ios",
  "appVersion": "1.0.0"
}
```

Rules:

- `externalDeviceId` is only for mobile device inventory
- it is never used as `targetDeviceId`
- repeated register calls for the same `(user, externalDeviceId)` update the same mobile device record

## 3. Desktop Pairing

### Desktop creates pair session

- `POST /v1/pairing/sessions`

```json
{
  "deviceLabel": "User MacBook Pro",
  "platform": "macos",
  "runtimeVersion": "1.0.0"
}
```

Response includes:

- `sessionId`
- `desktopDevice.id`
- `pairingCode`
- `pairingToken`
- `expiresAt`
- `qrText`
- `qrDataUrl`

Desktop pairing is Pro-only. If the backend returns `desktop_plan_required`, the mobile UI should hide the desktop connect / claim entry point for that account and surface the Pro plan state instead of retrying pairing.

### Mobile claims pair session

- `POST /v1/pairing/sessions/:sessionId/claim`

```json
{
  "pairingCode": "123456",
  "mobileDevice": {
    "label": "User iPhone",
    "platform": "ios",
    "appVersion": "1.0.0"
  }
}
```

### Desktop polls claim completion

- `GET /v1/pairing/sessions/:sessionId`
- Header: `x-pairing-token: <pairingToken>`

Notes:

- expiry only blocks unclaimed sessions
- once a session is claimed, desktop may continue polling until it reads `runtimeAuth`
- mobile inventory stays owned by `POST /v1/devices/mobile/register`; pairing claim does not create a duplicate mobile device row

Frontend note:

- Read `subscription.planCode` from backend truth before showing any desktop connect affordance
- Treat `planCode === "pro"` as the only plan that can expose pairing, runtime registration, or desktop task dispatch
- Treat `targetStatus === "plan_restricted"` and `targetErrorCode === "desktop_plan_required"` as plan gating, not connectivity failure
- Do not infer desktop availability from local state, cached UI state, or hardcoded plan lists

Once `status === "claimed"`, response includes:

```json
{
  "runtimeAuth": {
    "deviceId": "uuid",
    "deviceSecret": "derived-secret"
  }
}
```

## 4. Desktop Runtime Session

- `POST /v1/runtime/register`
- `POST /v1/runtime/heartbeat`
- `POST /v1/runtime/disconnect`
- `GET /v1/runtime/session`
- `GET /v1/runtime/tasks/assigned`
- `POST /v1/runtime/tasks/:taskId/status`
- `POST /v1/runtime/tasks/:taskId/artifacts`

Runtime register body:

```json
{
  "deviceId": "uuid",
  "deviceSecret": "derived-secret",
  "runtimeVersion": "1.0.0",
  "capabilities": ["browser", "filesystem", "mcp"]
}
```

Register response includes:

- `tokens.accessToken`
- `realtime.websocketPath`
- `realtime.ssePath`

Runtime lifecycle rules:

- `POST /v1/runtime/register` only creates a fresh connection-bound runtime token and invalidates any older runtime connection for the same desktop device
- desktop is not ready immediately after `register`; readiness truth flips only after websocket connect to `GET /v1/realtime/runtime` or a fallback `POST /v1/runtime/heartbeat`
- `GET /v1/runtime/session` includes a `readiness` object so desktop can verify backend truth without reusing user endpoints
- explicit `POST /v1/runtime/disconnect` closes the active runtime connection and invalidates further task delivery for that token

## 5. Mobile Bootstrap

- `GET /v1/mobile/bootstrap`
- `GET /v1/billing/plans`
- `GET /v1/billing/summary`
- `GET /v1/billing/profile`
- `PUT /v1/billing/profile`
- `POST /v1/billing/checkout/init`
- `GET /v1/billing/checkouts/:referenceId`
- `POST /v1/billing/store/verify`
- `POST /v1/billing/subscription/change-plan`
- `POST /v1/billing/subscription/cancel`

This is the dashboard truth payload. It returns:

- `user`
- `subscription`
- `usage`
- `brain`
- `devices`
- `recentTasks`
- `summary`

Truth rules:

- mobile should read active plan state from `GET /v1/mobile/bootstrap.subscription`
- mobile should read plan intelligence from `GET /v1/mobile/bootstrap.subscription.brainProfile`
- mobile should read usage counters from `GET /v1/mobile/bootstrap.usage`
- `GET /v1/auth/me.subscription` is the fallback truth surface when bootstrap is not available
- `GET /v1/auth/me.usage` is the fallback usage-truth surface when bootstrap is not available
- `GET /v1/auth/me.brain.chat.homeSurface` is the fallback signed-in landing truth when bootstrap is not available
- after a native Apple/Google purchase, mobile should call `POST /v1/billing/store/verify` and then refresh `GET /v1/mobile/bootstrap` or `GET /v1/auth/me`
- mobile must not infer active plan state from checkout status, billing history, or local cached UI state

Each `devices[]` item includes target eligibility fields:

- `id`
- `type`
- `isOnline`
- `canReceiveTasks`
- `targetStatus`: `ready`, `offline`, `inactive`, `backend_unreachable`, `not_desktop`
- `targetErrorCode`: `null`, `device_offline`, `device_inactive`, `backend_unreachable`, `invalid_target`

Important:

- mobile must send `devices[].id` as `targetDeviceId`
- mobile should only allow `type === "desktop"` and `canReceiveTasks === true`
- `isOnline === true` is not enough on its own; task targeting should require `canReceiveTasks === true`
- if `/healthz.network.externalClientsCanReachAdvertisedBaseUrl !== true`, desktop targets fail closed as `backend_unreachable`

`brain` is the backend truth for the Elyan chat surface. It includes:

- `chat.dispatchPath`
- `chat.brainProfilePath`
- `chat.realtimePath`
- `chat.activeSharedModel`
- `chat.activeUserModel`
- `chat.localProviderHint`
- `chat.sessionsPath`
- `chat.messagesPath`
- `chat.inferenceReady`
- `chat.isChatUsable`
- `retrieval.readyDocuments`
- `retrieval.readyChunks`

Mobile should prefer the `/v1/chat` contract for conversational UI:

- `GET /v1/chat/sessions`
- `POST /v1/chat/sessions`
- `GET /v1/chat/sessions/:sessionId`
- `POST /v1/chat/messages`

Backend still relays these chat requests through the existing task/runtime flow, so the desktop runtime remains the real execution surface.
When `POST /v1/chat/messages` returns, update the visible token meter immediately from `response.usage.tokensRemaining`, `response.usage.tokensUsed`, `response.usage.tokenBalance`, and `response.usage.tokensGrantedThisPeriod`. `response.usage.pendingTokens` is the backend-estimated debit for the just-created queued chat task, and `response.usage.tokenBalanceIncludesPending == true` means the returned balance already includes that pending debit. Do not wait for local estimates or task polling to update the token UI.

Notes:

- `chat.isChatUsable` is the UI gate for keeping the composer open
- `chat.activeSharedModel` is advisory and must not be used as the only readiness gate
- `chat.warmupJobId` can remain non-null while `chat.isChatUsable` stays true
- If `response.usage` contains legacy `aiCredits*` or `credit*` fields, ignore them for labels and counters; those fields are compatibility-only.
- After the task reaches a terminal state, refresh `/v1/auth/me` or `/v1/mobile/bootstrap` to reconcile the pending estimate with the committed token ledger.

`recentTasks` is a lightweight task feed item. Each item includes:

- `id`
- `title`
- `status`
- `targetDeviceId`
- `queuePosition`
- `requestedCapabilities`
- `summary`
- `error`
- `approvalRequest`
- `createdAt`
- `startedAt`
- `completedAt`
- `canceledAt`
- `updatedAt`

## 6. Tasks

- `POST /v1/tasks`
- `GET /v1/tasks`
- `GET /v1/tasks/:taskId`
- `POST /v1/tasks/:taskId/cancel`
- `POST /v1/tasks/:taskId/approval`

Create body:

```json
{
  "targetDeviceId": "uuid",
  "title": "Analyze this spreadsheet",
  "payload": {
    "prompt": "Summarize and flag anomalies",
    "source": "mobile"
  },
  "requestedCapabilities": ["filesystem"]
}
```

Optional retry header:

- `Idempotency-Key: <stable-client-key>`

Rules:

- `payload.prompt` is required
- `payload.source` is `mobile` or `desktop`
- `targetDeviceId` must be the desktop device `id` from `/v1/mobile/bootstrap.devices`
- if the desktop exists but is not connected, backend returns `409 device_offline`
- if the desktop is inactive, backend returns `409 device_inactive`
- if the desktop does not satisfy the requested capabilities, backend returns `409 runtime_capability_mismatch`
- if the backend advertises a local-only `APP_BASE_URL`, backend returns `409 backend_unreachable`
- if the id is not a valid desktop target, backend returns `422 invalid_target`
- if the same `Idempotency-Key` is retried with the same payload, backend returns the original task instead of creating a duplicate
- if the same `Idempotency-Key` is reused for a different payload, backend returns `409 idempotency_conflict`

Notes:

- `GET /v1/tasks` returns the same lightweight task feed shape used by `recentTasks`
- `GET /v1/tasks/:taskId` is the full detail route with `task`, `events`, and `artifacts`
- `artifacts[]` are the return channel for server-produced outputs such as summaries, PDFs, images, and docx-style exports
- For private or local work, the actual file creation still happens in the desktop/runtime path; backend only stores and relays artifact truth
- Mobile should read artifact rendering from backend truth only:
  - `contentType` decides the viewer type
  - `textContent` is the fast inline preview path
  - `viewerHint` is an additive backend hint for `text`, `markdown`, `pdf`, `image`, `document`, `structured`, or `file`
  - `previewText` is the compact inline preview and should be preferred over re-deriving previews on the client
  - `payload` can carry structured export metadata or encoded content
  - `storageKey` is an opaque download reference and must not be inferred locally
- When a desktop/runtime job finishes, mobile should refresh `GET /v1/tasks/:taskId` or listen for `task.artifacts` over realtime instead of rebuilding the artifact locally
- The backend already owns routing and task truth; mobile should only preprocess readable input and render the returned artifact truth

Task statuses:

- `queued`
- `planning`
- `running`
- `waiting_approval`
- `completed`
- `failed`
- `canceled`

## 7. Realtime for Mobile

- `GET /v1/realtime/stream`

Optional query:

- `taskId=<uuid>`
- `deviceId=<uuid>`

Rules:

- send at most one filter per stream request
- stream starts with `retry: 3000`
- first event is `ready`

Event types:

- `ready`
- `ping`
- `task.queued`
- `task.updated`
- `task.canceled`
- `task.approval_granted`
- `pairing.claimed`

Task event payloads are intentionally lightweight:

- `task.queued`, `task.updated`, `task.canceled` include `data.task`
- `task.approval_granted` includes `data.task`, `data.taskId`, `data.approved`, and optional `data.notes`
- mobile should fall back to `GET /v1/tasks/:taskId` only when it needs full execution detail

## 8. Boundary Notes

- account and subscription truth is server-side
- plan checkout, subscription upgrade, cancellation, callback, and webhook handling now live under `/v1/billing/*`
- iyzico customer profile state is separate from auth profile state; mobile should complete `/v1/billing/profile` before starting paid checkout
- billing callback and webhook routes are public backend surfaces; mobile should never attempt to sign or emulate them client-side
- execution truth is desktop-side
- this backend does not expose LLM provider setup, MCP management, skill management, or third-party OAuth integration APIs
- repo-internal AI, integrations, or MCP modules are not part of the published mobile dependency contract unless they are explicitly mounted in `src/app/build-app.ts`

## 9. Billing Flow

- Use `GET /v1/billing/plans` to render the 2 sellable plans: `solo`, `pro`
- Do not treat `GET /v1/billing/summary` as the primary plan-truth API for mobile; use `/v1/mobile/bootstrap.subscription` or `/v1/auth/me.subscription` instead
- `solo` is `$7/month`; `pro` is `$18/month`
- `solo` is the standard brain profile: `reasoningMultiplier: 1`
- `pro` is the premium brain profile: `reasoningMultiplier: 5`, larger bounded memory/retrieval fanout, and a bounded richer response budget
- Treat `GET /v1/billing/plans` as cacheable catalog truth; refresh it only on app boot, after a successful purchase, or when the user explicitly opens billing settings
- Use `GET /v1/billing/profile` / `PUT /v1/billing/profile` to read and complete the iyzico billing identity payload
- Start checkout with `POST /v1/billing/checkout/init`

Example checkout init body:

```json
{
  "planCode": "pro"
}
```

Optional retry header:

- `Idempotency-Key: <stable-client-key>`

- Backend response returns a checkout `referenceId` plus `launchUrl`
- repeated `Idempotency-Key` retries return the original checkout session instead of creating a second provider checkout
- Mobile should treat checkout as an external-link flow: open `launchUrl` in a browser/webview, then refresh `/v1/mobile/bootstrap` or `/v1/auth/me` to observe the authoritative plan state
- Paid checkout completion lands on `/v1/billing/callbacks/iyzico`; recurring renewals/failures land on `/v1/billing/webhooks/iyzico`
- For native Apple/Google purchases, do not poll billing endpoints repeatedly; call `POST /v1/billing/store/verify` once after the store purchase succeeds, then refresh `/v1/mobile/bootstrap` or `/v1/auth/me` exactly once
- Upgrades use `POST /v1/billing/subscription/change-plan`
- Cancellation uses `POST /v1/billing/subscription/cancel`
- Legacy `team` records are normalized to `pro` on the backend; mobile must not branch on `team` or show it as a selectable plan.
- Mobile must not compute its own intelligence tier from local state; it should display and gate from `subscription.brainProfile`.

## Frontend Developer Note

- Keep billing UI bound to the server truth from `/v1/mobile/bootstrap.subscription` and `/v1/billing/plans`.
- Render only `solo` and `pro` cards.
- Never hardcode plan prices or Apple/Google product logic in Flutter; read plan prices from backend truth and let the platform store drive payment UI.
- When an older account returns `team`, treat it as `pro` in labels, limits, and upgrade logic.
- Use `subscription.brainProfile` as the visible/behavioral intelligence source; do not hardcode pro-only routing behavior in Flutter.
- Do not add any new `team` copy, route, or button state back into the mobile UI.

## Document, OCR, and PDF Sync Note

Frontend developer should keep the mobile app on established, stable SDKs and thin native bridges:

- Auth: `google_sign_in`, `sign_in_with_apple`
- File picker / local source selection: `file_picker`, `image_picker`, `path_provider`, `cross_file`
- Image compression before upload: `flutter_image_compress`
- OCR / text extraction: `google_mlkit_text_recognition` when cross-platform is enough, plus a thin iOS Swift bridge over `VisionKit` and `Vision` for higher-quality native scanning
- Image-to-data / image labeling: `google_mlkit_image_labeling`
- Light image decode / stats / fallback summaries: `image`
- PDF creation and preview: `pdf`, `printing`
- iOS document type plumbing: `UniformTypeIdentifiers`, `PDFKit`
- Any optional cloud SDKs, including OpenAI, should stay behind a feature flag or fallback path and must not replace backend truth or local-readable preprocessing
- `brain.chat.mobileDocumentExportReady == true` means plain text-to-PDF, text-to-Word, or similar export requests can stay on the mobile local path. Do not force desktop pairing for those prompts.
- For pure local exports, the mobile client should attach `metadata.documentExportMode = "mobile_local"` and should not attach a desktop target.

Data flow rules:

- When the user attaches a document, image, screenshot, or export file, preprocess it on the device first.
- Extract readable text, page chunks, short summary, language tags, image labels, simple color/dimension stats, and safe metadata locally.
- Send the backend only readable payloads via `POST /v1/brain/knowledge/documents` using `text` and/or `chunks`; do not send raw binary as the primary brain input.
- Keep sending readable attachment metadata inside `POST /v1/chat/messages.metadata.attachments[]`; current-message attachments are the primary inference context for summarize, analyze, Q&A, and semantic edit requests.
- Map user-uploaded content to `sourceType: "manual"`, task or desktop output to `sourceType: "task_artifact"`, external links to `sourceType: "external_url"`, dataset imports to `sourceType: "dataset"`, and feedback-driven corrections to `sourceType: "feedback"`.
- Unless the user explicitly asks for desktop filesystem access, desktop save-to-disk, Desktop, Downloads, Documents, or another local path target, do not send `targetDeviceId`. No-desktop attachment flows must stay on `server_brain`.
- For pure content generation or summarization from already-readable text, keep the request on the shared-brain path and let the mobile app build the PDF or document locally. Do not request desktop capabilities.
- For local filesystem work or explicit desktop save targets, include the matching capability hints in the task payload so the backend can fail closed correctly:
  - read / inspect local files: `document_read`
  - write / save / overwrite local files: `document_write`
- For requests like “metni PDF olarak ver”, “bu metni Word’e çevir”, or “özeti PDF yap”, the mobile app should:
  - keep the export local,
  - render the returned text into the existing canvas/export flow,
  - produce the PDF with `pdf` + `printing`,
  - and only mirror the readable text/chunks to `POST /v1/brain/knowledge/documents` if the content should become searchable knowledge.
- Keep `contentHash`, `mimeType`, `pageCount`, `originalName`, and `clientArtifactId` mirrored into `metadata.compactDocument` when you build the request body, because the backend strips unknown top-level fields.
- If the same content is turned into a PDF, also mirror the underlying readable text/chunks into the brain knowledge path so retrieval and PDF output stay in sync.
- In follow-up prompts, re-sending the same attachment is still preferred, but single-document sessions no longer require it. The backend now reuses the latest unique attachment context from the same chat session when the request stays unambiguous.
- After a successful PDF or document sync, refresh backend truth once with `GET /v1/mobile/bootstrap` or `GET /v1/auth/me`; do not derive plan, token, or brain state locally.

Recommended mobile behavior:

- Keep previews fast and local.
- Keep uploads compact by deduplicating repeated pages or repeated OCR paragraphs before sending.
- Preserve the backend as the source of truth for token usage, plan state, and brain readiness.
- Prefer the backend’s `brain.chat.mobileDocumentExportReady` hint over local heuristics when deciding whether a text-only export should remain on device.

## V1 Release Status (2026-06-15)

Live-verified on `api.elyan.dev`. All items below are production-confirmed.

### Canonical Endpoints

- Knowledge documents: `POST /v1/brain/knowledge/documents` — use this path; `/v1/knowledge/documents` is not mounted.
- Chat messages: `POST /v1/chat/messages` with field `content` (not `prompt`).
- Mobile device register: `POST /v1/devices/mobile/register` — returns 200 with the registered device; the `client_metadata` column migration is applied.

### targetDeviceId Rules

- Only send `targetDeviceId` when the user explicitly requests desktop filesystem access (save to disk, open local path, Desktop/Downloads/Documents).
- For all attachment/summary/analysis/export flows where `needsDesktop=false`, omit `targetDeviceId`.
- `documentExportMode="mobile_local"` guarantees `needsDesktop=false` even if `selectedDeviceId` is set in app state.

### Reattach

- For single-document chat sessions, the backend recovers the attachment context from session history automatically.
- You only need to re-send `metadata.attachments` in the current message when there are multiple candidate documents and you want to disambiguate.
- Follow-up prompts like "bunu daha resmi yaz" work without re-attaching when `attachmentContextSource: "session_recovery"` appears in the response.

### Export Flow

- Send `metadata.documentExportMode: "mobile_local"` in the follow-up export prompt.
- The backend returns `renderRecipe` with `format: "pdf"` and `text_blocks` containing the actual previous assistant answer, not a transient ack.
- Render the `text_blocks` content into a PDF on-device using `pdf` + `printing`.
- Do not wait for a desktop runtime; the export shortcut bypasses model inference entirely.
