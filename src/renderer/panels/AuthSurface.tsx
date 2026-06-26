import { useState } from 'react';

type AuthMode = 'login' | 'register';

const TERMS_OF_SERVICE_URL = 'https://elyan.dev/kullanim-kosullari';
const PRIVACY_POLICY_URL = 'https://elyan.dev/gizlilik';

export interface LegalAcceptance {
  termsAccepted: boolean;
  privacyAccepted: boolean;
}

interface AuthSurfaceProps {
  heroImageUrl: string;
  runtimeReady: boolean;
  runtimeDegraded?: boolean;
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
  onSubmitAuth: (legalAcceptance?: LegalAcceptance) => void;
  onRetryRuntime?: () => void;
}

export function AuthSurface({
  heroImageUrl,
  runtimeReady,
  runtimeDegraded = false,
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
  onRetryRuntime,
}: AuthSurfaceProps) {
  const [legalDialogOpen, setLegalDialogOpen] = useState(false);
  const [termsAccepted, setTermsAccepted] = useState(false);
  const [privacyAccepted, setPrivacyAccepted] = useState(false);
  const legalReady = termsAccepted && privacyAccepted;

  function requestAuthSubmit() {
    if (authMode === 'register') {
      setTermsAccepted(false);
      setPrivacyAccepted(false);
      setLegalDialogOpen(true);
      return;
    }
    onSubmitAuth();
  }

  function confirmLegalAcceptance() {
    if (!legalReady) {
      return;
    }
    setLegalDialogOpen(false);
    onSubmitAuth({ termsAccepted: true, privacyAccepted: true });
  }

  return (
    <main className="auth-surface" aria-label="Elyan auth">
      <section className="auth-panel">
        <div className="auth-copy">
          <h1>Elyan</h1>
          <p>{runtimeReady ? 'Giriş veya hesap' : runtimeDegraded ? 'Bağlantı kurulamadı' : 'Yerel runtime hazırlanıyor'}</p>
        </div>

        {!runtimeReady ? (
          runtimeDegraded ? (
            <div className="auth-loading auth-loading--degraded" role="status" aria-live="assertive">
              <strong>Runtime bağlantısı başarısız</strong>
              <p>Yerel Elyan bağlantısı kurulamadı. Uygulamayı yeniden başlatmayı deneyin.</p>
              {onRetryRuntime ? (
                <button type="button" className="auth-retry-btn" onClick={onRetryRuntime}>
                  Yeniden dene
                </button>
              ) : null}
            </div>
          ) : (
            <div className="auth-loading" role="status" aria-live="polite" aria-busy="true">
              <div className="auth-loading__spinner" aria-hidden="true" />
              <strong>Runtime hazırlanıyor</strong>
              <p>Yerel Elyan bağlantısı kurulduğunda giriş kutuları açılacak.</p>
            </div>
          )
        ) : (
          <form
            className="auth-minimal-form"
            onSubmit={(event) => {
              event.preventDefault();
              requestAuthSubmit();
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
                type="email"
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
            {authMode === 'register' ? (
              <p className="auth-legal-note">Hesap oluştururken Kullanım Koşulları ve Gizlilik Politikası kabul edilir.</p>
            ) : null}
          </form>
        )}
      </section>

      <section className="auth-logo-panel" aria-hidden="true">
        <img className="auth-mascot" src={heroImageUrl} alt="" />
      </section>
      {legalDialogOpen ? (
        <div className="auth-legal-overlay" role="dialog" aria-modal="true" aria-labelledby="auth-legal-title">
          <div className="auth-legal-card">
            <strong id="auth-legal-title">Yasal onay</strong>
            <p>Devam etmek için Elyan kullanım koşullarını ve gizlilik politikasını kabul etmelisin.</p>
            <div className="auth-legal-row">
              <input
                type="checkbox"
                checked={termsAccepted}
                onChange={(event) => setTermsAccepted(event.currentTarget.checked)}
                aria-label="Kullanım koşullarını kabul ediyorum"
              />
              <span>
                <a href={TERMS_OF_SERVICE_URL} target="_blank" rel="noopener noreferrer">
                  Kullanım Koşulları
                </a>
                'nı kabul ediyorum.
              </span>
            </div>
            <div className="auth-legal-row">
              <input
                type="checkbox"
                checked={privacyAccepted}
                onChange={(event) => setPrivacyAccepted(event.currentTarget.checked)}
                aria-label="Gizlilik politikasını kabul ediyorum"
              />
              <span>
                <a href={PRIVACY_POLICY_URL} target="_blank" rel="noopener noreferrer">
                  Gizlilik Politikası
                </a>
                'nı kabul ediyorum.
              </span>
            </div>
            <div className="auth-legal-actions">
              <button type="button" onClick={() => setLegalDialogOpen(false)}>
                Vazgeç
              </button>
              <button type="button" className="auth-legal-confirm" disabled={!legalReady} onClick={confirmLegalAcceptance}>
                Kabul et ve devam et
              </button>
            </div>
          </div>
        </div>
      ) : null}
    </main>
  );
}
