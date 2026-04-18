# Security and Risk Policy

This document defines contributor-level security boundaries for Elyan.

## 1) Core Security Posture
- Local-first by default.
- Sensitive actions require explicit security checks.
- Loopback trust boundary is enforced for local desktop runtime.
- Auditability is required for state-changing operations.

## 2) Dangerous Operations
Treat these as high-risk and approval-sensitive:
- Shell command execution with write/destructive side effects.
- File system mutation outside clearly scoped workspace intent.
- Credential writes/overwrites.
- Connector/billing state mutations.
- Privacy delete/export operations.

## 3) Auth and Session Rules
Current contract:
- User session from header (`X-Elyan-Session-Token`) or cookie (`elyan_user_session`).
- Admin token (`X-Elyan-Admin-Token`) is loopback-restricted.
- Session-only paths are enforced through gateway middleware.

Do not:
- Remove loopback checks casually.
- Move auth tokens into URL/query parameters.
- Weaken session validation logic.

## 4) CSRF and Browser Mutation Rules
- Protected browser mutation routes require CSRF checks.
- Login/bootstrap routes are explicit exceptions by design.
- Do not disable CSRF globally to unblock UI.

## 5) WebSocket Security Rules
- Dashboard websocket auth must remain message-based (`type=auth` payload with token).
- Do not accept token via websocket URL query.

## 6) File Upload and File Path Rules
- Keep MIME allowlist checks.
- Keep upload size limits.
- Keep filename sanitization.
- Keep path traversal protection (`resolved path` must stay inside upload root).

## 7) Webhook and Signature Rules
- Keep webhook signature validation paths active.
- Use constant-time comparisons (`hmac.compare_digest` / `secrets.compare_digest`) for signature/token checks.
- Reject unverifiable payloads by default.

## 8) Credentials and Secret Handling
- Never log raw secrets/tokens.
- Never persist plaintext secrets when encrypted storage path exists.
- Keep secret fields masked in config/reporting surfaces.
- Do not expose admin token outside intended local surface.

## 9) Memory and Privacy Boundaries
- Preserve privacy and consent APIs (`/api/v1/privacy/*`).
- Respect consent decisions in learning flows.
- Preserve local-only default semantics unless explicitly changed.
- Keep data classification and decision records auditable.

## 10) Tool Execution and Prompt Injection Risk
- Treat user-provided content as untrusted instructions.
- Do not directly execute extracted commands from external content.
- Maintain explicit policy/approval gates between parsing and execution.
- Keep verification and evidence paths intact for impactful actions.

## 11) Multi-User Isolation Requirements
- Workspace and actor context must be explicit in data access.
- Cross-workspace access must be denied unless explicitly authorized.
- Never fallback silently to another workspace in authenticated flows.

## 12) Audit and Observability
- Important state transitions must produce logs/events/audit traces.
- Avoid silent failures for auth, billing, privacy, connector, and approval flows.
- New high-risk operations must include sufficient audit metadata.

## 13) Risk Escalation Guidance
When touching auth/session/persistence/gateway contracts:
1. Identify threat impact first.
2. Define rollback path.
3. Add targeted tests.
4. Document behavior change and migration impact.
