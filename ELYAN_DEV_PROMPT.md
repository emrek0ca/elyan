# Elyan.dev Launch Prompt

You are working inside the Elyan codebase at `/Users/emrekoca/Desktop/bot`.

Your goal is to finish and harden the public `elyan.dev` surface without restarting the project or breaking the existing local-first core.

## Product model

Elyan has three layers:

1. Local agent runtime
2. Shared VPS control plane
3. Hosted web surface at `elyan.dev`

Keep private local context local by default. Do not centralize user-private memory on the VPS. The control plane is for accounts, billing, subscriptions, entitlements, credits, and hosted access.

## What already exists

- Public site routes: `/`, `/platform`, `/docs`, `/docs/[slug]`, `/download`, `/pricing`, `/about`, `/contact`
- Hosted panel routes: `/panel`, `/panel/account`, `/panel/billing`, `/panel/usage`, `/panel/notifications`
- Hosted auth and control-plane APIs are in place
- PostgreSQL-backed control-plane state exists
- The local build currently passes `lint`, `test`, and `build`

## What to finish

1. Verify the public site is polished, coherent, and fully linked.
2. Verify the hosted panel and billing flow explain themselves cleanly when iyzico credentials are missing.
3. If credentials are available, wire the hosted billing path end to end.
4. If VPS access is available, complete the `elyan.dev` DNS cutover and confirm nginx/systemd health.
5. Keep the site honest: no fake controls, no placeholder screens, no dead routes.
6. Keep the architecture narrow: do not expand the control plane into private memory storage.

## Constraints

- Do not restart from scratch.
- Do not remove the local-first runtime.
- Do not turn the VPS into a personal brain or document store.
- Do not add new dependencies unless they are clearly required.
- Prefer small, safe refactors over broad rewrites.
- Preserve existing working chat, retrieval, citations, and control-plane behavior.

## Acceptance criteria

- `elyan.dev` publicly serves the polished marketing + hosted access experience.
- Hosted billing clearly handles both configured and unconfigured iyzico states.
- The site makes the difference between local runtime, VPS control plane, and hosted surface obvious.
- The app still builds and runs locally.
- The final report names any remaining blocker explicitly.

## Local verification

Run these from the repo root:

```bash
npm install
npm run lint
npm run test
npm run build
npm run dev
```

If production-style startup is needed:

```bash
npm run start
```

## Reporting format

When you finish, report only:

- what changed in architecture
- what belongs local vs VPS vs hosted
- what you designed for pricing/token accounting
- what code you changed
- what can be tested locally right now
- the exact commands to run
- the last real blocker, if any

