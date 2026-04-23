'use client';

import { FormEvent, useEffect, useState } from 'react';
import { signIn, signOut } from 'next-auth/react';

type Mode = 'login' | 'register';

type SessionState =
  | {
      authenticated: false;
    }
  | {
      authenticated: true;
      session: {
        userId?: string;
        email?: string;
        name?: string;
        accountId?: string;
        ownerType?: string;
        role?: string;
        planId?: string;
      };
        account: {
          displayName: string;
          balanceCredits: string;
          subscription: {
            planId: string;
            status: string;
          };
          entitlements: {
            hostedAccess: boolean;
            hostedUsageAccounting: boolean;
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
      };

type SessionResponse = {
  ok: boolean;
  session: {
    userId?: string;
    email?: string;
    name?: string;
    accountId?: string;
    ownerType?: string;
    role?: string;
    planId?: string;
  };
    account: {
      displayName: string;
      balanceCredits: string;
      subscription: {
        planId: string;
        status: string;
      };
      entitlements: {
        hostedAccess: boolean;
        hostedUsageAccounting: boolean;
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
  };

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
    });
  }

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setFeedback(null);
    setIsSubmitting(true);

    try {
      if (mode === 'register') {
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
            Elyan keeps the local runtime private. This surface only binds hosted access, billing, and shared control-plane state.
          </p>
        </div>

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

          <button className="auth-form__submit" type="submit" disabled={isSubmitting}>
            {mode === 'register' ? 'Create account' : 'Login'}
          </button>
        </form>

        {feedback ? <div className="auth-page__feedback">{feedback}</div> : null}

        <div className="auth-page__session-card">
          <div>
            <div className="auth-page__session-label">Current session</div>
            <div className="auth-page__session-value">
              {sessionState.authenticated ? sessionState.session.email : 'No active hosted session'}
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
              <strong>{sessionState.account.subscription.status}</strong>
            </div>
            <div className="auth-page__detail">
              <span>Role</span>
              <strong>{sessionState.session.role ?? 'owner'}</strong>
            </div>
            <div className="auth-page__detail">
              <span>Hosted access</span>
              <strong>{sessionState.account.entitlements.hostedAccess ? 'enabled' : 'disabled'}</strong>
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
              <span>Resets</span>
              <strong>{new Date(sessionState.account.usageSnapshot.resetAt).toLocaleString()}</strong>
            </div>
          </div>
        ) : null}
      </div>
    </div>
  );
}
