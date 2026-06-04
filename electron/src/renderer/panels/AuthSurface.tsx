type AuthMode = 'login' | 'register';

interface AuthSurfaceProps {
  heroImageUrl: string;
  authMode: AuthMode;
  authEmail: string;
  authPassword: string;
  authDisplayName: string;
  authBusy: boolean;
  authError: string;
  onAuthModeChange: (mode: AuthMode) => void;
  onAuthEmailChange: (value: string) => void;
  onAuthPasswordChange: (value: string) => void;
  onAuthDisplayNameChange: (value: string) => void;
  onSubmitAuth: () => void;
}

export function AuthSurface({
  heroImageUrl,
  authMode,
  authEmail,
  authPassword,
  authDisplayName,
  authBusy,
  authError,
  onAuthModeChange,
  onAuthEmailChange,
  onAuthPasswordChange,
  onAuthDisplayNameChange,
  onSubmitAuth,
}: AuthSurfaceProps) {
  return (
    <main className="auth-surface" aria-label="Elyan auth">
      <section className="auth-panel">
        <div className="auth-copy">
          <h1>Elyan</h1>
          <p>Giriş veya hesap</p>
        </div>

        <form
          className="auth-minimal-form"
          onSubmit={(event) => {
            event.preventDefault();
            onSubmitAuth();
          }}
        >
          <div className="auth-tabs" role="tablist" aria-label="Auth mode">
            <button type="button" className={authMode === 'login' ? 'is-active' : ''} onClick={() => onAuthModeChange('login')}>
              Giriş
            </button>
            <button type="button" className={authMode === 'register' ? 'is-active' : ''} onClick={() => onAuthModeChange('register')}>
              Kayıt
            </button>
          </div>

          <div className="auth-fields">
            {authMode === 'register' ? (
              <input
                value={authDisplayName}
                onChange={(event) => onAuthDisplayNameChange(event.currentTarget.value)}
                placeholder="Ad soyad"
                autoComplete="name"
                aria-label="Ad soyad"
              />
            ) : null}
            <input
              value={authEmail}
              onChange={(event) => onAuthEmailChange(event.currentTarget.value)}
              placeholder="E-posta"
              autoComplete="email"
              inputMode="email"
              aria-label="E-posta"
            />
            <input
              value={authPassword}
              onChange={(event) => onAuthPasswordChange(event.currentTarget.value)}
              placeholder="Şifre"
              type="password"
              autoComplete={authMode === 'login' ? 'current-password' : 'new-password'}
              aria-label="Şifre"
            />
          </div>
          {authError ? <div className="auth-error">{authError}</div> : null}

          <button type="submit" className="auth-continue" disabled={authBusy || !authEmail.trim() || !authPassword.trim()}>
            <svg viewBox="0 0 20 20" aria-hidden="true">
              <path d="M11.6 4.7 16.9 10l-5.3 5.3-1-1 3.5-3.6H3.2V9.3h10.9l-3.5-3.6 1-1Z" />
            </svg>
            <span>{authBusy ? 'Bağlanıyor' : 'Devam et'}</span>
          </button>
        </form>
      </section>

      <section className="auth-logo-panel" aria-hidden="true">
        <img className="auth-mascot" src={heroImageUrl} alt="" />
      </section>
    </main>
  );
}
