# Billing Integration

This backend is ready for iyzico web checkout plus native Apple/Google store verification.

## What the backend owns

- plan catalog truth
- billing profile storage
- iyzico product/pricing-plan synchronization
- checkout session creation and persistence
- hosted checkout callback completion
- recurring webhook verification and subscription state updates
- plan upgrade and cancellation
- task, token, desktop, and brain-profile limit enforcement

## Required env

- `IYZICO_API_KEY`
- `IYZICO_SECRET_KEY`
- `IYZICO_MERCHANT_ID`
- `IYZICO_BASE_URL`
- `IYZICO_PUBLIC_BASE_URL`
- `APPLE_APP_STORE_ISSUER_ID`
- `APPLE_APP_STORE_KEY_ID`
- `APPLE_APP_STORE_PRIVATE_KEY`
- `APPLE_APP_BUNDLE_ID`
- `GOOGLE_PLAY_PACKAGE_NAME`
- `GOOGLE_PLAY_SERVICE_ACCOUNT_EMAIL`
- `GOOGLE_PLAY_PRIVATE_KEY`

`IYZICO_PUBLIC_BASE_URL` must be a public HTTPS origin in production because iyzico callback and webhook URLs must be reachable by iyzico.

## Sellable plans

- `solo`: `$7/month`, no desktop connection, 600 included tokens, standard brain profile
- `pro`: `$18/month`, 3 desktops, 2,000 included tokens, premium brain profile

The internal fallback plan is `free`. It is not a sellable pricing-card plan but is kept as the default user state before purchase.
Legacy `team` rows are normalized to `pro` by the backend and must not be exposed as a sellable plan.

## Plan intelligence

- `subscription.brainProfile` is backend-owned plan truth.
- `solo` uses `reasoningMultiplier: 1`, standard retrieval fanout, and the base response-token budget.
- `pro` uses `reasoningMultiplier: 5`, larger bounded retrieval/memory fanout, and a bounded token scale for richer answers.
- Clients must not infer intelligence level locally; they should render and route from backend subscription/bootstrap truth.

## Frontend contract

1. Read plans from `GET /v1/billing/plans`
2. Read current state from `GET /v1/billing/summary`
3. Collect customer identity via `GET/PUT /v1/billing/profile`
4. Start checkout with `POST /v1/billing/checkout/init`
5. Open `launchUrl`
6. Poll `GET /v1/billing/checkouts/:referenceId`

## Backend notes

- iyzico plan references are created lazily through the backend the first time a sellable plan is needed
- native Apple/Google purchases are verified through `/v1/billing/store/verify`; the backend only validates receipts and persists the resulting subscription truth
- keep plan listing cacheable on the client; do not poll billing state unless a purchase or plan change actually happened
- subscription callback completion updates `subscriptions` truth and checkout session truth together
- recurring webhook notifications validate `X-IYZ-SIGNATURE-V3`
- task creation is blocked when the monthly plan limit is exhausted
- desktop claim is blocked when the current plan desktop limit is exhausted
