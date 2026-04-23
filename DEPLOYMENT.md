# Deployment

README is the canonical product truth.

This file is only for advanced deployment.

## Shipping Baseline

Elyan ships directly as a Next.js / Node.js runtime.

No Docker is required for the main user path.

## Local Baseline

Use the README flow first:

```bash
cp .env.example .env
npm install
npm run dev
```

## Advanced VPS Path

Only relevant if you are using the optional shared control plane.

Owned Elyan paths:

- `/srv/elyan/current`
- `/srv/elyan/releases/<version>`
- `/srv/elyan/.env`
- `/srv/elyan/storage`
- PostgreSQL via `DATABASE_URL`
- systemd service `elyan`

## Required For Optional Hosted Control Plane

- `DATABASE_URL`
- `NEXTAUTH_URL`
- `NEXTAUTH_SECRET`
- `IYZICO_API_KEY`
- `IYZICO_SECRET_KEY`
- `IYZICO_MERCHANT_ID`

## Health Endpoints

- `/api/healthz`
- `/api/capabilities`
- `/api/control-plane/health`

## Validation

```bash
npm run lint
npm run test
npm run build
```
