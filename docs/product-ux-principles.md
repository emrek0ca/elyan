# Product UX Principles

UX direction for Elyan desktop and operator surfaces.

## 1) Product Truth
- Elyan must show real runtime state, not aspirational state.
- If a capability is unavailable, show that explicitly.
- Distinguish "configured" vs "connected" vs "healthy".

## 2) Visual Direction
- Clean, minimal, premium.
- Calm hierarchy and spacing over dense dashboard clutter.
- Use concise labels and meaningful status signals.

## 3) Interaction Principles
- Every primary screen should answer: "What can I do now safely?"
- Keep critical actions obvious and reversible.
- Avoid hidden side effects in seemingly simple controls.

## 4) Onboarding Principles
- Onboarding must mirror actual backend gates:
  - account bootstrap/login,
  - provider/model readiness,
  - channel readiness,
  - first routine,
  - draft review state.
- Never claim completion if `setup_complete` and readiness checks are not satisfied.

## 5) Routine and Learned Draft UX
- Learned drafts must be visible, reviewable, and explicitly promotable.
- Promotion outcomes should be immediate and understandable.
- Routine status must expose enabled state, schedule, and run history clearly.

## 6) Error UX
- Replace generic failure messages with actionable errors.
- Show whether issue is:
  - auth/session,
  - provider/model,
  - channel/integration,
  - runtime/dependency,
  - validation/policy.
- Do not suppress important backend errors.

## 7) Trust and Safety UX
- Dangerous actions require explicit user confidence and clear language.
- Show why a request is blocked (policy/security/privacy), not only that it failed.
- Preserve user trust by being explicit about limits.

## 8) Multi-User UX Readiness
- Workspace context should be explicit where relevant.
- Role/permission boundaries should be reflected in available actions.
- Avoid local-single-user assumptions in UI copy where multi-user routes exist.

## 9) Anti-Patterns to Avoid
- Fake "AI working" states without real backend progress.
- Overloaded screens with duplicate controls.
- Long instructional paragraphs instead of actionable state.
- "Everything green" dashboards while critical subsystems are degraded.

## 10) Contributor Checklist for UX Changes
1. Does this UI expose real runtime state?
2. Does it preserve onboarding/auth contracts?
3. Does it reduce cognitive load?
4. Are blocked/error states understandable?
5. Does it avoid introducing false capability signals?
