# Elyan Website — Hostinger Node.js Deployment

This package is a self-hosted Astro Node application. It has no Vercel, Netlify, Supabase, Firebase, or browser-token dependency. The browser talks only to the same-origin Elyan BFF; the BFF talks to `api.elyan.dev`.

## Runtime requirement

The Hostinger account must show **Websites → Add website → Node.js Apps / Deploy Web App** (wording can vary). Hostinger currently provides Node.js web-app deployment on Business and Cloud plans. A static file upload is not enough for Elyan auth, refresh-token cookies, billing mutations, or SSE.

Web checkout also requires the existing Elyan control-plane deployment to report its Iyzico checkout configuration as enabled in `/readyz`. These provider secrets belong on the backend server, never in Hostinger or browser variables.

If this option is absent, do not upload a static-token build. Keep the ZIP and enable/upgrade to a Hostinger plan with Node.js Web Apps first.

## Upload

1. In hPanel, choose **Add website → Node.js Apps / Deploy Web App**.
2. Choose **Upload your website files** and upload `release/elyan-website-hostinger.zip`.
3. Select **Node.js 22**.
4. Set the install/build command to `npm ci && npm run build`.
5. Set the start command to `node dist/server/entry.mjs`.
6. Attach the production domain `elyan.dev` and require HTTPS.
7. Add the environment variables below before the build. Public OAuth values are compiled by Astro during `npm run build`.
8. Deploy, then open `/app/login` and run the smoke checklist.

## Environment variables

Required:

```dotenv
NODE_ENV=production
ELYAN_API_BASE_URL=https://api.elyan.dev
ELYAN_WEB_ORIGIN=https://elyan.dev
ELYAN_WEB_SESSION_SECRET=<at-least-32-random-characters>
PUBLIC_GOOGLE_CLIENT_ID=<Google-Web-client-id>
PUBLIC_APPLE_SERVICE_ID=<Apple-Service-ID>
PUBLIC_APPLE_REDIRECT_URI=https://elyan.dev/app/login
```

Hostinger normally supplies `PORT`. If the panel asks for bind settings, add:

```dotenv
HOST=0.0.0.0
```

Generate the session secret locally with `openssl rand -base64 48`. Never commit or paste the real value into `.env.example`.

## Provider panels

- Google Identity Services authorized JavaScript origin: `https://elyan.dev`
- Google authorized redirect/origin configuration must use the same production hostname.
- Apple Service ID website domain: `elyan.dev`
- Apple return URL: the exact value configured in `PUBLIC_APPLE_REDIRECT_URI`
- The Elyan backend remains responsible for Google/Apple signature, audience, issuer, and expiry validation.

## Production smoke checklist

1. `https://elyan.dev/` renders the marketing site.
2. `/app/login` returns CSP/security headers and sets only a readable CSRF cookie.
3. Register with explicit Terms and Privacy acceptance.
4. Sign out; confirm `/app` redirects to `/app/login`.
5. Sign in (and verify the real 2FA challenge when enabled).
6. Send one message; verify the sidebar session and completed response survive reload.
7. Open two tabs; verify SSE resume does not regress a completed answer to “running”.
8. Pair a desktop code and confirm readiness under **Settings → Devices**.
9. Open Billing; confirm plan/token/task values match the mobile/backend account.
10. Start one connector OAuth flow and return to **Settings → Integrations**.

Health checks for the control plane:

```bash
curl -fsS https://api.elyan.dev/healthz
curl -fsS https://api.elyan.dev/readyz
```

Do not expose access/refresh tokens in hPanel logs, browser storage, query strings, or support screenshots.
