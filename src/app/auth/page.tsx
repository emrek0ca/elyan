'use client';

import { FormEvent, useEffect, useState } from 'react';
import { signIn, signOut } from 'next-auth/react';

type Mode = 'login' | 'register';

type SessionSnapshot = {
  userId?: string;
  email?: string;
  name?: string;
  accountId?: string;
  ownerType?: string;
  role?: string;
  planId?: string;
  accountStatus?: string;
  subscriptionStatus?: string;
  subscriptionSyncState?: string;
  hostedAccess?: boolean;
  hostedUsageAccounting?: boolean;
};

type AccountSnapshot = {
  displayName: string;
  balanceCredits: string;
  subscription: {
    planId: string;
    status: string;
    syncState: string;
  };
  entitlements: {
    hostedAccess: boolean;
    hostedUsageAccounting: boolean;
  };
  deviceSummary?: {
    total: number;
    pending: number;
    active: number;
    revoked: number;
    expired: number;
  };
  usageSnapshot: {
    dailyRequests: number;
    dailyRequestsLimit: number;
    remainingRequests: number;
    dailyHostedToolActionCalls: number;
    dailyHostedToolActionCallsLimit: number;
    remainingHostedToolActionCalls: number;
    monthlyCreditsRemaining: string;
    monthlyCreditsBurned: string;
    resetAt: string;
    state: string;
  };
};

type SessionState =
  | {
      authenticated: false;
    }
  | {
      authenticated: true;
      session: SessionSnapshot;
      account: AccountSnapshot;
      profile?: {
        session: SessionSnapshot;
      };
    };

type SessionResponse = {
  ok: boolean;
  session: SessionSnapshot;
  account: AccountSnapshot;
  profile?: {
    session: SessionSnapshot;
  };
};

const HOSTED_UNAVAILABLE_CODE = 'hosted_identity_unavailable';

const initialSessionState: SessionState = {
  authenticated: false,
};

export default function AuthPage() {
  const [mode, setMode] = useState<Mode>('login');
  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const [displayName, setDisplayName] = useState('');
  const [planId, setPlanId] = useState('local_byok');
  const [feedback, setFeedback] = useState<string | null>(null);
  const [sessionState, setSessionState] = useState<SessionState>(initialSessionState);
  const [hostedAuthAvailable, setHostedAuthAvailable] = useState(true);
  const [isSubmitting, setIsSubmitting] = useState(false);

  useEffect(() => {
    void loadSession();
  }, []);

  async function loadSession() {
    const response = await fetch('/api/control-plane/auth/me', {
      credentials: 'include',
      cache: 'no-store',
    });

    if (!response.ok) {
      if (response.status === 503) {
        const body = (await response.json().catch(() => null)) as { code?: string; error?: string } | null;
        if (body?.code === HOSTED_UNAVAILABLE_CODE) {
          setHostedAuthAvailable(false);
          setSessionState(initialSessionState);
          setFeedback(
            'Hosted identity is not configured on this machine. Elyan is running in local mode only.'
          );
          return;
        }
      }

      setSessionState(initialSessionState);
      return;
    }

    const body = (await response.json()) as SessionResponse;

    if (!body.ok) {
      setSessionState(initialSessionState);
      return;
    }

    setSessionState({
      authenticated: true,
      session: body.session,
      account: body.account,
      profile: body.profile,
    });
    setHostedAuthAvailable(true);
  }

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setFeedback(null);
    setIsSubmitting(true);

    try {
      if (mode === 'register') {
        if (!hostedAuthAvailable) {
          setFeedback('Hosted identity is disabled in local mode.');
          return;
        }

        const response = await fetch('/api/control-plane/auth/register', {
          method: 'POST',
          headers: {
            'Content-Type': 'application/json',
          },
          body: JSON.stringify({
            email,
            password,
            displayName,
            ownerType: 'individual',
            planId,
          }),
        });

        const body = (await response.json()) as { ok: boolean; error?: string };
        if (!response.ok || !body.ok) {
          setFeedback(body.error ?? 'Registration failed');
          return;
        }
      }

      if (!hostedAuthAvailable) {
        setFeedback('Hosted identity is disabled in local mode.');
        return;
      }

      const result = await signIn('credentials', {
        email,
        password,
        redirect: false,
      });

      if (!result || result.error) {
        setFeedback(result?.error ?? 'Login failed');
        return;
      }

      await loadSession();
      setFeedback(mode === 'register' ? 'Account created and session started.' : 'Session started.');
    } finally {
      setIsSubmitting(false);
    }
  }

  async function handleLogout() {
    await signOut({
      redirect: false,
    });
    setSessionState(initialSessionState);
    setFeedback('Session cleared.');
  }

  return (
    <div className="auth-page">
      <div className="auth-page__card">
        <div className="auth-page__header">
          <div className="auth-page__eyebrow">Hosted identity</div>
          <h1 className="auth-page__title">Account, session, and hosted entitlements</h1>
          <p className="auth-page__lead">
            Elyan keeps the local runtime private. When hosted auth is configured, this surface binds hosted access,
            billing, and device sync on elyan.dev. Otherwise Elyan stays in local mode.
          </p>
        </div>

        {!hostedAuthAvailable ? (
          <div className="auth-page__feedback auth-page__feedback--neutral">
            Local mode is active. Set `DATABASE_URL` and `NEXTAUTH_SECRET` only if you want hosted account and billing
            features.
          </div>
        ) : null}

        <div className="auth-page__mode-switch" role="tablist" aria-label="Auth mode">
          <button
            type="button"
            className={mode === 'login' ? 'auth-page__mode auth-page__mode--active' : 'auth-page__mode'}
            onClick={() => setMode('login')}
          >
            Login
          </button>
          <button
            type="button"
            className={mode === 'register' ? 'auth-page__mode auth-page__mode--active' : 'auth-page__mode'}
            onClick={() => setMode('register')}
          >
            Register
          </button>
        </div>

        <form className="auth-form" onSubmit={handleSubmit}>
          {mode === 'register' ? (
            <>
              <label className="auth-form__field">
                <span>Display name</span>
                <input value={displayName} onChange={(event) => setDisplayName(event.target.value)} required />
              </label>

              <label className="auth-form__field">
                <span>Plan</span>
                <select value={planId} onChange={(event) => setPlanId(event.target.value)}>
                  <option value="local_byok">Local / BYOK</option>
                  <option value="cloud_assisted">Cloud-Assisted</option>
                  <option value="pro_builder">Pro / Builder</option>
                  <option value="team_business">Team / Business</option>
                </select>
              </label>
            </>
          ) : null}

          <label className="auth-form__field">
            <span>Email</span>
            <input type="email" value={email} onChange={(event) => setEmail(event.target.value)} required />
          </label>

          <label className="auth-form__field">
            <span>Password</span>
            <input type="password" value={password} onChange={(event) => setPassword(event.target.value)} minLength={12} required />
          </label>

          <button className="auth-form__submit" type="submit" disabled={isSubmitting || !hostedAuthAvailable}>
            {mode === 'register' ? 'Create account' : 'Login'}
          </button>
        </form>

        {feedback ? <div className="auth-page__feedback">{feedback}</div> : null}

        <div className="auth-page__session-card">
          <div>
            <div className="auth-page__session-label">Current session</div>
            <div className="auth-page__session-value">
              {sessionState.authenticated
                ? sessionState.session.email
                : hostedAuthAvailable
                  ? 'No active hosted session'
                  : 'Local mode only'}
            </div>
          </div>

          {sessionState.authenticated ? (
            <button type="button" className="auth-page__logout" onClick={handleLogout}>
              Logout
            </button>
          ) : null}
        </div>

        {sessionState.authenticated ? (
          <div className="auth-page__details">
            <div className="auth-page__detail">
              <span>Account</span>
              <strong>{sessionState.account.displayName}</strong>
            </div>
            <div className="auth-page__detail">
              <span>Plan</span>
              <strong>{sessionState.account.subscription.planId}</strong>
            </div>
            <div className="auth-page__detail">
              <span>Subscription</span>
              <strong>{sessionState.session.subscriptionStatus ?? sessionState.account.subscription.status}</strong>
            </div>
            <div className="auth-page__detail">
              <span>Role</span>
              <strong>{sessionState.session.role ?? 'owner'}</strong>
            </div>
            <div className="auth-page__detail">
              <span>Hosted access</span>
              <strong>
                {sessionState.session.hostedAccess ?? sessionState.account.entitlements.hostedAccess
                  ? 'enabled'
                  : 'disabled'}
              </strong>
            </div>
            <div className="auth-page__detail">
              <span>Sync state</span>
              <strong>{sessionState.session.subscriptionSyncState ?? sessionState.account.subscription.syncState}</strong>
            </div>
            <div className="auth-page__detail">
              <span>Credits</span>
              <strong>{sessionState.account.balanceCredits}</strong>
            </div>
            <div className="auth-page__detail">
              <span>Daily requests</span>
              <strong>
                {sessionState.account.usageSnapshot.dailyRequests}/{sessionState.account.usageSnapshot.dailyRequestsLimit}
              </strong>
            </div>
            <div className="auth-page__detail">
              <span>Tool calls</span>
              <strong>
                {sessionState.account.usageSnapshot.dailyHostedToolActionCalls}/{sessionState.account.usageSnapshot.dailyHostedToolActionCallsLimit}
              </strong>
            </div>
            <div className="auth-page__detail">
              <span>Devices</span>
              <strong>{sessionState.account.deviceSummary?.total ?? 0}</strong>
            </div>
            <div className="auth-page__detail">
              <span>Resets</span>
              <strong>{new Date(sessionState.account.usageSnapshot.resetAt).toLocaleString()}</strong>
            </div>
          </div>
        ) : null}
      </div>
    </div>
  );
}
