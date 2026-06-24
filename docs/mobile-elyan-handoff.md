# Elyan Mobile Handoff

Mobile is a thin client. It does not own billing UI, token math, model routing, or local execution.

## What changed on the backend

- Elyan's main brain is now the server-owned control-plane model, not a separate mobile-side feature.
- The backend publishes a stable brain profile at `GET /v1/brain/profile`.
- The backend publishes token and usage truth at `GET /v1/auth/me` and `GET /v1/mobile/bootstrap`.
- Billing/plan surfaces stay dormant for mobile.
- Chat and task routing use the same backend decision path.
- Brain runtime readiness is fail-safe and can fall back between serving providers without exposing provider internals to the user.

## What mobile should read

Use these endpoints as the only truth sources:

- `GET /v1/auth/me`
- `GET /v1/mobile/bootstrap`
- `GET /v1/brain/profile`

### Token Truth

Render only the bar/state from `usage`:

- `dailyLimit`
- `dailyUsed`
- `dailyRemaining`
- `dailyResetAt`
- `dailyProgressPercent`
- `weeklyLimit`
- `weeklyUsed`
- `weeklyRemaining`
- `weeklyResetAt`
- `weeklyProgressPercent`
- `budgetState`: `normal`, `conserve`, or `critical`
- `meteringPolicy`: backend-owned accounting metadata

Do not compute token limits locally. Do not increment counters in the app. Do not infer reset times from client clocks.
`pendingUsageIsEstimate=true` means the send response may reserve an estimated amount until the completed task publishes actual provider usage. Replace the estimate with the next backend usage snapshot; never accumulate it locally.

The backend now keeps normal chat concise, opens a larger bounded response budget only when the user explicitly requests a long or detailed answer, and automatically returns to the normal budget near the end of the allowance. Mobile must not send its own `maxTokens`, context-window, or response-length override.

### Brain truth

Use these fields for chat readiness and UI state:

- `brain.chat.inferenceReady`
- `brain.chat.servingProvider`
- `brain.chat.baseModel`
- `brain.chat.activeAdapter`
- `brain.chat.warmupJobId`
- `brain.chat.serverBrainName`
- `brain.chat.mobileDocumentExportReady`
- `brain.training.pipeline.runtimeReady`
- `brain.training.pipeline.promotion`
- `brain.sections.model`
- `brain.sections.routing`
- `brain.sections.learning`

`brain.chat.serverBrainName` is the user-facing name. It is `Elyan`.

## UI rules

- Do not show pricing, plans, upsell, or billing CTA.
- Do not expose hostnames, internal paths, or provider-specific infrastructure details.
- Treat `usage` as the token truth.
- Treat `brain.chat.inferenceReady` as a normal state, not a blocking or scary state.
- If token allowance is exhausted, show a short safe message only.
- If Elyan is temporarily unavailable, show a short safe failure message only.

## Chat connection flow

1. Call `GET /v1/auth/me`.
2. Call `GET /v1/mobile/bootstrap`.
3. Read `brain.chat.homeSurface` for the initial landing surface.
4. Read `brain.chat.messagesPath` for the chat composer/send path.
5. Read `brain.chat.realtimePath` for live updates.
6. Send chat/messages through the existing backend contract only.
7. Do not invent a second model routing layer in the app.

## Task flow

- Mobile creates tasks through `POST /v1/tasks`.
- The backend decides whether the task goes to desktop or Elyan.
- Plain text export prompts like `metni PDF olarak ver` should stay on the mobile local path when `brain.chat.mobileDocumentExportReady == true`.
- For those exports, attach `metadata.documentExportMode = "mobile_local"` and do not attach a desktop target or `document_write` hint unless the user explicitly points to a local filesystem path.
- The mobile app should only render status, result, and short error text.
- The app should not try to decide token allowance or routing itself.

## Document Processing Note

When the frontend developer updates the mobile document/attachment pipeline, keep the stack thin and local:

- OCR: `google_mlkit_text_recognition`
- Image labels / image-to-data: `google_mlkit_image_labeling`
- Image decode / stats / visual fallback: `image`
- PDF output: `pdf` + `printing`
- Optional native iOS scan bridges can use `VisionKit` and `Vision`

Always send readable payloads only. Put `contentHash`, `mimeType`, `pageCount`, `originalName`, and `clientArtifactId` inside `metadata.compactDocument` as well, because backend schema validation ignores unknown top-level fields.

## Error mapping

Map backend codes to short user-facing text:

- `daily_quota_reached` -> `Günlük token hakkı doldu.`
- `weekly_quota_reached` -> `Haftalık token hakkı doldu.`
- `desktop_required` -> `Bu yerel dosya işlemi için masaüstü gerekiyor.`
- `device_offline` -> `Masaüstü şu anda çevrimdışı.`
- `runtime_capability_mismatch` -> `Bu görev için uygun masaüstü yok.`
- `server_brain_unavailable` -> `Elyan şu anda yanıt veremiyor.`

Do not surface raw host, provider, or trace details to the user.
