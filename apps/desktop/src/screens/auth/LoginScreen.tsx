import { useState } from "react";
import { ArrowRight, ExternalLink } from "lucide-react";
import { useNavigate } from "react-router-dom";

import { ElyanMark } from "@/components/brand/ElyanMark";
import { Button } from "@/components/primitives/Button";
import { Surface } from "@/components/primitives/Surface";
import { loginLocalUser } from "@/services/api/elyan-service";
import { runtimeManager } from "@/runtime/runtime-manager";
import { useUiStore } from "@/stores/ui-store";

const ELYAN_DEV_URL = "https://elyan.dev";

export function LoginScreen() {
  const navigate = useNavigate();
  const signIn = useUiStore((state) => state.signIn);
  const completeOnboarding = useUiStore((state) => state.completeOnboarding);
  const defaultEmail = useUiStore((state) => state.authenticatedEmail);
  const [email, setEmail] = useState(defaultEmail);
  const [password, setPassword] = useState("");
  const [error, setError] = useState("");
  const [submitting, setSubmitting] = useState(false);

  async function openSignup() {
    const opened = await runtimeManager.openExternalUrl(ELYAN_DEV_URL);
    if (!opened) {
      window.open(ELYAN_DEV_URL, "_blank", "noopener,noreferrer");
    }
  }

  async function handleContinue() {
    const normalizedEmail = email.trim().toLowerCase();
    if (!normalizedEmail) {
      setError("Devam etmek için e-posta gir.");
      return;
    }
    if (!password.trim()) {
      setError("Şifre gerekli.");
      return;
    }
    setSubmitting(true);
    setError("");
    try {
      const user = await loginLocalUser(normalizedEmail, password);
      signIn(user.email);
      completeOnboarding();
      navigate("/home", { replace: true });
    } catch (authError) {
      setError(authError instanceof Error ? authError.message : "Giriş başarısız.");
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <div className="flex min-h-[calc(100vh-44px)] items-center justify-center px-6 py-10">
      <Surface tone="hero" className="w-full max-w-[980px] px-8 py-10 md:px-12 md:py-12">
        <div className="grid items-center gap-12 md:grid-cols-[0.95fr_1.05fr]">
          <div className="flex justify-center md:justify-start">
            <ElyanMark size="xl" className="h-[220px] w-[220px] rounded-[40px]" alt="Elyan logo" />
          </div>

          <div className="max-w-[440px] space-y-6">
            <div className="space-y-3">
              <div className="text-[11px] uppercase tracking-[0.18em] text-[var(--text-tertiary)]">Elyan</div>
              <h1 className="font-display text-[40px] font-semibold tracking-[-0.05em] text-[var(--text-primary)]">
                Hoş geldin
              </h1>
              <p className="text-[14px] leading-7 text-[var(--text-secondary)]">
                Masaüstü shell’e girmek için yerel hesapla giriş yap. Kayıtlı değilsen hesap açma akışı `elyan.dev` üzerinden yürür.
              </p>
            </div>

            <div className="space-y-3">
              <label className="block text-[11px] uppercase tracking-[0.16em] text-[var(--text-tertiary)]">E-posta</label>
              <input
                type="email"
                value={email}
                onChange={(event) => {
                  setEmail(event.target.value);
                  if (error) {
                    setError("");
                  }
                }}
                placeholder="you@company.com"
                className="h-[52px] w-full rounded-[20px] border border-[var(--border-subtle)] bg-[color-mix(in_srgb,var(--bg-surface)_94%,var(--bg-surface-raised))] px-5 text-[15px] text-[var(--text-primary)] outline-none transition focus:border-[var(--border-focus)]"
                onKeyDown={(event) => {
                  if (event.key === "Enter") {
                    event.preventDefault();
                    void handleContinue();
                  }
                }}
              />
            </div>

            <div className="space-y-3">
              <label className="block text-[11px] uppercase tracking-[0.16em] text-[var(--text-tertiary)]">Şifre</label>
              <input
                type="password"
                value={password}
                onChange={(event) => {
                  setPassword(event.target.value);
                  if (error) {
                    setError("");
                  }
                }}
                placeholder="Şifren"
                className="h-[52px] w-full rounded-[20px] border border-[var(--border-subtle)] bg-[color-mix(in_srgb,var(--bg-surface)_94%,var(--bg-surface-raised))] px-5 text-[15px] text-[var(--text-primary)] outline-none transition focus:border-[var(--border-focus)]"
                onKeyDown={(event) => {
                  if (event.key === "Enter") {
                    event.preventDefault();
                    void handleContinue();
                  }
                }}
              />
              {error ? <div className="text-[12px] text-[var(--state-warning)]">{error}</div> : null}
            </div>

            <div className="flex flex-wrap gap-3">
              <Button variant="primary" onClick={() => void handleContinue()} disabled={submitting}>
                {submitting ? "Giriş yapılıyor" : "Giriş yap"}
                <ArrowRight className="ml-2 h-4 w-4" />
              </Button>
              <Button variant="secondary" onClick={() => void openSignup()} disabled={submitting}>
                Kayıt ol
                <ExternalLink className="ml-2 h-4 w-4" />
              </Button>
            </div>
          </div>
        </div>
      </Surface>
    </div>
  );
}
