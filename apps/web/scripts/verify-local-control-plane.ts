/**
 * Local hosted-control-plane verification script.
 * Layer: diagnostics. Critical probe that checks health, registration, login, session, and panel behavior.
 */
import { randomUUID } from 'crypto';
import { execFileSync } from 'child_process';
import { existsSync, mkdtempSync, readFileSync, rmSync } from 'fs';
import { tmpdir } from 'os';
import { join } from 'path';
import { parse as parseEnv } from 'dotenv';

type ProbeResult = {
  status: number;
  timeMs: number;
  body: string;
};

type ReportEntry = {
  label: string;
  ok: boolean;
  detail: string;
};

function loadLocalEnvFiles() {
  const candidates = [
    join(process.cwd(), '.env.local'),
    join(process.cwd(), '.env'),
    join(process.cwd(), '..', '.env.local'),
    join(process.cwd(), '..', '.env'),
  ];

  for (const file of candidates) {
    if (!existsSync(file)) {
      continue;
    }

    const parsed = parseEnv(readFileSync(file, 'utf8'));
    for (const [key, value] of Object.entries(parsed)) {
      if (!process.env[key]) {
        process.env[key] = value;
      }
    }
  }
}

loadLocalEnvFiles();

const baseUrl = (process.env.CONTROL_PLANE_BASE_URL ?? process.env.NEXT_PUBLIC_API_BASE_URL ?? 'http://127.0.0.1:3013').replace(/\/+$/, '');
function fail(message: string): never {
  throw new Error(message);
}

function shortText(value: string, max = 220) {
  const compact = value.replace(/\s+/g, ' ').trim();
  if (compact.length <= max) {
    return compact;
  }

  return `${compact.slice(0, max - 1)}…`;
}

function request(method: string, path: string, options?: { body?: string; cookieJar?: string }): ProbeResult {
  const tempDir = mkdtempSync(join(tmpdir(), 'elyan-control-plane-'));
  const bodyPath = join(tempDir, 'body.json');
  const headersPath = join(tempDir, 'headers.txt');

  try {
    const args = ['-sS', '-o', bodyPath, '-D', headersPath, '-w', '%{http_code} %{time_total}', '-X', method];
    if (options?.cookieJar) {
      args.push('-c', options.cookieJar, '-b', options.cookieJar);
    }

    if (options?.body) {
      args.push('-H', 'content-type: application/json', '--data', options.body);
    }

    args.push(`${baseUrl}${path}`);

    const output = execFileSync('curl', args, { encoding: 'utf8' }).trim();
    const [statusText = '0', timeText = '0'] = output.split(/\s+/, 2);
    const body = readFileSync(bodyPath, 'utf8');

    return {
      status: Number(statusText) || 0,
      timeMs: Math.round((Number(timeText) || 0) * 1000),
      body,
    };
  } finally {
    rmSync(tempDir, { recursive: true, force: true });
  }
}

function requestForm(path: string, form: URLSearchParams, options?: { cookieJar?: string }): ProbeResult {
  const tempDir = mkdtempSync(join(tmpdir(), 'elyan-control-plane-'));
  const bodyPath = join(tempDir, 'body.json');
  const headersPath = join(tempDir, 'headers.txt');

  try {
    const args = ['-sS', '-o', bodyPath, '-D', headersPath, '-w', '%{http_code} %{time_total}', '-X', 'POST'];
    if (options?.cookieJar) {
      args.push('-c', options.cookieJar, '-b', options.cookieJar);
    }

    args.push('-H', 'content-type: application/x-www-form-urlencoded', '--data', form.toString(), `${baseUrl}${path}`);

    const output = execFileSync('curl', args, { encoding: 'utf8' }).trim();
    const [statusText = '0', timeText = '0'] = output.split(/\s+/, 2);
    const body = readFileSync(bodyPath, 'utf8');

    return {
      status: Number(statusText) || 0,
      timeMs: Math.round((Number(timeText) || 0) * 1000),
      body,
    };
  } finally {
    rmSync(tempDir, { recursive: true, force: true });
  }
}

async function main() {
  const reports: ReportEntry[] = [];
  const tempDir = mkdtempSync(join(tmpdir(), 'elyan-control-plane-verify-'));
  const cookieJar = join(tempDir, 'cookies.txt');
  const email = `local-probe+${Date.now()}-${randomUUID().slice(0, 8)}@example.com`;
  const password = 'ProbePassword123!';
  const displayName = 'Local Probe';
  const databaseUrl = process.env.DATABASE_URL;

  try {
    const healthz = request('GET', '/api/healthz');
    const healthzJson = JSON.parse(healthz.body) as { ok?: boolean; ready?: boolean };
    reports.push({
      label: 'healthz',
      ok: healthz.status === 200 && healthzJson.ok === true && healthzJson.ready === true,
      detail: `status=${healthz.status} time=${healthz.timeMs}ms ready=${String(healthzJson.ready)}`,
    });

    const controlPlaneHealth = request('GET', '/api/control-plane/health');
    const controlPlaneJson = JSON.parse(controlPlaneHealth.body) as {
      ok?: boolean;
      databaseConfigured?: boolean;
      postgresReachable?: boolean;
      migrationsApplied?: boolean;
      schemaReady?: boolean;
      authConfigured?: boolean;
      billingConfigured?: boolean;
      hostedReady?: boolean;
      activeDatabaseMode?: string;
      missingEnvKeys?: string[];
    };
    const controlPlaneOk =
      controlPlaneHealth.status === 200 &&
      controlPlaneJson.ok === true &&
      controlPlaneJson.databaseConfigured === true &&
      controlPlaneJson.postgresReachable === true &&
      controlPlaneJson.migrationsApplied === true &&
      controlPlaneJson.schemaReady === true &&
      controlPlaneJson.authConfigured === true &&
      controlPlaneJson.activeDatabaseMode === 'postgres';
    reports.push({
      label: 'control-plane-health',
      ok: controlPlaneOk,
      detail:
        `status=${controlPlaneHealth.status} time=${controlPlaneHealth.timeMs}ms ` +
        `db=${String(controlPlaneJson.databaseConfigured)} reachable=${String(controlPlaneJson.postgresReachable)} ` +
        `migrations=${String(controlPlaneJson.migrationsApplied)} schema=${String(controlPlaneJson.schemaReady)} ` +
        `auth=${String(controlPlaneJson.authConfigured)} hosted=${String(controlPlaneJson.hostedReady)} ` +
        `mode=${String(controlPlaneJson.activeDatabaseMode)} missing=${(controlPlaneJson.missingEnvKeys ?? []).join('|') || '-'}`,
    });

    if (controlPlaneJson.billingConfigured !== true || controlPlaneJson.hostedReady !== true) {
      reports.push({
        label: 'control-plane-hosted-ready',
        ok: true,
        detail: `warn billingConfigured=${String(controlPlaneJson.billingConfigured)} hostedReady=${String(controlPlaneJson.hostedReady)}`,
      });
    }

    const unauthMe = request('GET', '/api/control-plane/auth/me');
    let unauthMeOk = unauthMe.status === 401;
    let unauthMeBody = unauthMe.body;
    reports.push({
      label: 'auth-me-unauthenticated',
      ok: unauthMeOk,
      detail: `status=${unauthMe.status} time=${unauthMe.timeMs}ms body=${shortText(unauthMeBody || '') || '(empty)'}`,
    });

    const register = request('POST', '/api/control-plane/auth/register', {
      body: JSON.stringify({
        email,
        password,
        displayName,
        ownerType: 'individual',
        planId: 'local_byok',
      }),
    });
    const registerJson = register.body ? (JSON.parse(register.body) as { ok?: boolean; user?: { userId?: string; accountId?: string } }) : {};
    const dbDetail = databaseUrl ? 'db=env-present' : 'db=env-missing';
    reports.push({
      label: 'register',
      ok: register.status === 200 && registerJson.ok === true,
      detail:
        `status=${register.status} time=${register.timeMs}ms user=${String(registerJson.user?.userId ?? '-')}` +
        ` account=${String(registerJson.user?.accountId ?? '-')} ${dbDetail}` +
        ` body=${shortText(register.body)}`,
    });

    const csrf = request('GET', '/api/auth/csrf', { cookieJar });
    const csrfJson = JSON.parse(csrf.body) as { csrfToken?: string };
    if (!csrfJson.csrfToken) {
      fail('CSRF token was not returned by /api/auth/csrf');
    }

    const login = requestForm(
      '/api/auth/callback/credentials',
      new URLSearchParams({
        csrfToken: csrfJson.csrfToken,
        email,
        password,
        redirect: 'false',
        callbackUrl: `${baseUrl}/auth`,
      }),
      { cookieJar }
    );
    const sessionCookieLines = readFileSync(cookieJar, 'utf8')
      .split('\n')
      .filter((line) => line.includes('next-auth.session-token') || line.includes('__Secure-next-auth.session-token'));
    reports.push({
      label: 'login',
      ok: login.status === 302 && sessionCookieLines.length > 0,
      detail: `status=${login.status} time=${login.timeMs}ms cookie=${sessionCookieLines.length > 0 ? 'yes' : 'no'} body=${shortText(login.body) || '(empty)'}`,
    });

    const me = request('GET', '/api/control-plane/auth/me', { cookieJar });
    const meJson = JSON.parse(me.body) as { ok?: boolean; session?: { email?: string; accountId?: string } };
    reports.push({
      label: 'auth-me-authenticated',
      ok: me.status === 200 && meJson.ok === true && meJson.session?.email === email,
      detail: `status=${me.status} time=${me.timeMs}ms email=${String(meJson.session?.email ?? '-')}` + ` body=${shortText(me.body)}`,
    });

    const panel = request('GET', '/api/control-plane/panel', { cookieJar });
    const panelJson = JSON.parse(panel.body) as { ok?: boolean; account?: { accountId?: string }; session?: { email?: string } };
    reports.push({
      label: 'panel',
      ok: panel.status === 200 && panelJson.ok === true && panelJson.session?.email === email && Boolean(panelJson.account?.accountId),
      detail: `status=${panel.status} time=${panel.timeMs}ms account=${String(panelJson.account?.accountId ?? '-')} body=${shortText(panel.body)}`,
    });

    for (const entry of reports) {
      console.log(`${entry.ok ? 'PASS' : 'FAIL'} ${entry.label}: ${entry.detail}`);
    }

    const failures = reports.filter((entry) => !entry.ok);
    if (failures.length > 0) {
      fail(`Local control-plane verification failed: ${failures.map((entry) => entry.label).join(', ')}`);
    }

    console.log(`SUMMARY PASS email=${email}`);
  } finally {
    rmSync(tempDir, { recursive: true, force: true });
  }
}

main().catch((error) => {
  console.error(error instanceof Error ? error.message : String(error));
  process.exitCode = 1;
});
