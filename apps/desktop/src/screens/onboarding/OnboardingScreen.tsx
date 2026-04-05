import { type ReactNode, useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";

import { ElyanMark } from "@/components/brand/ElyanMark";
import { Button } from "@/components/primitives/Button";
import { Surface } from "@/components/primitives/Surface";
import { apiClient } from "@/services/api/client";
import { getProviderDescriptors, getSystemReadiness, saveProviderKey } from "@/services/api/elyan-service";
import { useUiStore } from "@/stores/ui-store";
import type { ProviderDescriptor, SystemReadiness } from "@/types/domain";

type Step = "welcome" | "account" | "model" | "done";
type CloudProviderId = "openai" | "anthropic" | "groq";

const cloudProviderOrder: CloudProviderId[] = ["openai", "anthropic", "groq"];

export function OnboardingScreen() {
  const navigate = useNavigate();
  const signIn = useUiStore((state) => state.signIn);
  const completeOnboarding = useUiStore((state) => state.completeOnboarding);

  const [step, setStep] = useState<Step>("welcome");
  const [displayName, setDisplayName] = useState("");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [passwordConfirm, setPasswordConfirm] = useState("");
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(false);
  const [modelSetupLoading, setModelSetupLoading] = useState(false);
  const [modelSetupBusy, setModelSetupBusy] = useState(false);
  const [modelSetupError, setModelSetupError] = useState("");
  const [modelSetupMessage, setModelSetupMessage] = useState("");
  const [selectedProvider, setSelectedProvider] = useState<CloudProviderId>("openai");
  const [providerKey, setProviderKey] = useState("");
  const [readiness, setReadiness] = useState<SystemReadiness | null>(null);
  const [providers, setProviders] = useState<ProviderDescriptor[]>([]);

  const ollamaProvider = providers.find((provider) => provider.providerId === "ollama") || null;
  const ollamaInstalledModels = (ollamaProvider?.models || []).filter((model) => model.installed);
  const configuredCloudProviders = cloudProviderOrder
    .map((providerId) => providers.find((provider) => provider.providerId === providerId))
    .filter((provider): provider is ProviderDescriptor => Boolean(provider?.authState === "ready"));

  useEffect(() => {
    if (step !== "model") {
      return;
    }
    void loadModelSetup();
  }, [step]);

  async function loadModelSetup() {
    setModelSetupLoading(true);
    setModelSetupError("");
    try {
      const [nextReadiness, nextProviders] = await Promise.all([getSystemReadiness(), getProviderDescriptors()]);
      setReadiness(nextReadiness);
      setProviders(nextProviders);
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : String(err);
      setModelSetupError(msg || "Model durumu alınamadı.");
    } finally {
      setModelSetupLoading(false);
    }
  }

  function finishOnboarding() {
    setStep("done");
    window.setTimeout(() => {
      completeOnboarding();
      navigate("/home", { replace: true });
    }, 600);
  }

  async function handleBootstrap() {
    setError("");
    const normalizedEmail = email.trim().toLowerCase();
    const normalizedName = displayName.trim() || normalizedEmail.split("@")[0];

    if (!normalizedEmail) {
      setError("E-posta gerekli.");
      return;
    }
    if (!password) {
      setError("Parola gerekli.");
      return;
    }
    if (password.length < 8) {
      setError("Parola en az 8 karakter olmalı.");
      return;
    }
    if (password !== passwordConfirm) {
      setError("Parolalar eşleşmiyor.");
      return;
    }

    setLoading(true);
    try {
      const result = await apiClient.request<{
        ok: boolean;
        session_token?: string;
        user?: { email: string };
        error?: string;
      }>("/api/v1/auth/bootstrap-owner", {
        method: "POST",
        body: {
          email: normalizedEmail,
          password,
          display_name: normalizedName,
          workspace_id: "local-workspace",
        },
      });

      if (!result.ok) {
        setError(result.error || "Hesap oluşturulamadı.");
        return;
      }

      if (result.session_token) {
        apiClient.setSessionToken(result.session_token);
      }

      signIn(normalizedEmail);
      setModelSetupMessage("");
      setModelSetupError("");
      setProviderKey("");
      setStep("model");
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : String(err);
      if (msg.includes("409") || msg.toLowerCase().includes("already completed")) {
        // Bootstrap was already done — navigate to login
        completeOnboarding();
        navigate("/login", { replace: true });
        return;
      }
      setError("Bir hata oluştu. Backend çalışıyor mu?");
    } finally {
      setLoading(false);
    }
  }

  async function handleSaveProviderKey() {
    const apiKey = providerKey.trim();
    if (!apiKey) {
      setModelSetupError("API key gerekli.");
      return;
    }
    setModelSetupBusy(true);
    setModelSetupError("");
    setModelSetupMessage("");
    try {
      const result = await saveProviderKey(selectedProvider, apiKey);
      if (!result.ok) {
        setModelSetupError(result.message || "API key kaydedilemedi.");
        return;
      }
      setModelSetupMessage(result.message || "Provider hazır.");
      finishOnboarding();
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : String(err);
      setModelSetupError(msg || "API key kaydedilemedi.");
    } finally {
      setModelSetupBusy(false);
    }
  }

  if (step === "welcome") {
    return (
      <div className="flex min-h-[calc(100vh-44px)] items-center justify-center px-6 py-10">
        <Surface tone="hero" className="w-full max-w-[900px] px-8 py-10 md:px-12 md:py-14">
          <div className="grid items-center gap-12 md:grid-cols-[0.9fr_1.1fr]">
            <div className="flex justify-center md:justify-start">
              <ElyanMark size="xl" className="h-[200px] w-[200px] rounded-[36px]" alt="Elyan" />
            </div>
            <div className="max-w-[440px] space-y-6">
              <div>
                <div className="mb-2 text-[11px] uppercase tracking-[0.18em] text-[var(--text-tertiary)]">İlk kurulum</div>
                <h1 className="font-display text-[38px] font-semibold leading-tight tracking-[-0.05em] text-[var(--text-primary)]">
                  Elyan'a hoş geldin
                </h1>
                <p className="mt-3 text-[14px] leading-7 text-[var(--text-secondary)]">
                  Bu cihazdaki ilk kurulumu yapıyorsun. Hesabını oluştur, Elyan hazır hale gelsin.
                </p>
              </div>
              <Button variant="primary" onClick={() => setStep("account")}>
                Başla →
              </Button>
            </div>
          </div>
        </Surface>
      </div>
    );
  }

  if (step === "model") {
    const selectedProviderLabel =
      providers.find((provider) => provider.providerId === selectedProvider)?.label || selectedProvider.toUpperCase();
    const ollamaSummary = ollamaInstalledModels[0]?.displayName || (readiness?.ollamaReady ? "Yerel host hazır" : "");

    return (
      <div className="flex min-h-[calc(100vh-44px)] items-center justify-center px-6 py-10">
        <Surface tone="hero" className="w-full max-w-[560px] px-8 py-10 md:px-10 md:py-12">
          <div className="space-y-6">
            <div>
              <div className="mb-2 text-[11px] uppercase tracking-[0.18em] text-[var(--text-tertiary)]">Model ayarla</div>
              <h2 className="font-display text-[28px] font-semibold tracking-tight text-[var(--text-primary)]">
                Çalışma motoru
              </h2>
              <p className="mt-2 text-[13px] leading-6 text-[var(--text-secondary)]">
                Yerel model hazırsa devam et. Değilse şimdi bir cloud provider anahtarı ekleyebilir ya da bu adımı atlayabilirsin.
              </p>
            </div>

            <div className="rounded-[20px] border border-[var(--border-subtle)] bg-[var(--bg-surface-alt)] p-5">
              {modelSetupLoading ? (
                <div className="text-[13px] text-[var(--text-secondary)]">Model durumu kontrol ediliyor…</div>
              ) : readiness?.ollamaReady ? (
                <div className="space-y-2">
                  <div className="text-[12px] uppercase tracking-[0.16em] text-[var(--text-tertiary)]">Ollama</div>
                  <div className="text-[16px] font-medium text-[var(--text-primary)]">
                    Ollama hazır{ollamaSummary ? `, model: ${ollamaSummary}` : "."}
                  </div>
                  <div className="text-[13px] text-[var(--text-secondary)]">
                    {ollamaInstalledModels.length
                      ? `${ollamaInstalledModels.length} local model kullanılabilir.`
                      : "Yerel host açık, istersen modelleri daha sonra Providers ekranından yönetebilirsin."}
                  </div>
                </div>
              ) : (
                <div className="space-y-4">
                  <div>
                    <div className="text-[12px] uppercase tracking-[0.16em] text-[var(--text-tertiary)]">Cloud provider</div>
                    <div className="mt-2 text-[14px] text-[var(--text-primary)]">
                      Ollama şu anda görünmüyor. İstersen bir API key ekleyip cloud lane’leri aç.
                    </div>
                    <div className="mt-1 text-[12px] text-[var(--text-secondary)]">
                      {configuredCloudProviders.length
                        ? `Hazır provider: ${configuredCloudProviders.map((provider) => provider.label).join(", ")}`
                        : readiness?.blockingIssue || "OpenAI, Anthropic veya Groq ile devam edebilirsin."}
                    </div>
                  </div>

                  <div className="flex flex-wrap gap-2">
                    {cloudProviderOrder.map((providerId) => {
                      const provider = providers.find((item) => item.providerId === providerId);
                      const isActive = selectedProvider === providerId;
                      return (
                        <button
                          key={providerId}
                          type="button"
                          onClick={() => setSelectedProvider(providerId)}
                          className={`rounded-full border px-3 py-2 text-[12px] uppercase tracking-[0.12em] transition ${
                            isActive
                              ? "border-[var(--border-focus)] bg-[var(--bg-surface)] text-[var(--text-primary)]"
                              : "border-[var(--border-subtle)] bg-transparent text-[var(--text-secondary)]"
                          }`}
                        >
                          {provider?.label || providerId}
                        </button>
                      );
                    })}
                  </div>

                  <input
                    type="password"
                    value={providerKey}
                    onChange={(event) => {
                      setProviderKey(event.target.value);
                      setModelSetupError("");
                    }}
                    placeholder={`${selectedProviderLabel} API key`}
                    className={inputCls}
                  />
                </div>
              )}
            </div>

            {modelSetupError ? <div className="text-[12px] text-[var(--state-warning)]">{modelSetupError}</div> : null}
            {modelSetupMessage ? <div className="text-[12px] text-[var(--text-secondary)]">{modelSetupMessage}</div> : null}

            <div className="flex flex-wrap gap-3">
              <Button variant="secondary" onClick={() => void loadModelSetup()} disabled={modelSetupLoading || modelSetupBusy}>
                Tekrar kontrol et
              </Button>
              <Button variant="ghost" onClick={() => finishOnboarding()} disabled={modelSetupBusy}>
                Atla
              </Button>
              <Button
                variant="primary"
                onClick={() => (readiness?.ollamaReady ? finishOnboarding() : void handleSaveProviderKey())}
                disabled={modelSetupLoading || modelSetupBusy}
              >
                {modelSetupBusy
                  ? "Kaydediliyor…"
                  : readiness?.ollamaReady
                    ? "Devam et →"
                    : "API key kaydet →"}
              </Button>
            </div>
          </div>
        </Surface>
      </div>
    );
  }

  if (step === "done") {
    return (
      <div className="flex min-h-[calc(100vh-44px)] items-center justify-center px-6 py-10">
        <Surface tone="hero" className="w-full max-w-[480px] px-8 py-10 text-center">
          <div className="space-y-4">
            <div className="text-[36px]">✓</div>
            <h2 className="font-display text-[26px] font-semibold tracking-tight text-[var(--text-primary)]">Hazır!</h2>
            <p className="text-[14px] text-[var(--text-secondary)]">Hesabın oluşturuldu. Yönlendiriliyor…</p>
          </div>
        </Surface>
      </div>
    );
  }

  // step === "account"
  return (
    <div className="flex min-h-[calc(100vh-44px)] items-center justify-center px-6 py-10">
      <Surface tone="hero" className="w-full max-w-[480px] px-8 py-10 md:px-10 md:py-12">
        <div className="space-y-6">
          <div>
            <div className="mb-2 text-[11px] uppercase tracking-[0.18em] text-[var(--text-tertiary)]">Hesap oluştur</div>
            <h2 className="font-display text-[28px] font-semibold tracking-tight text-[var(--text-primary)]">
              Yerel hesabın
            </h2>
            <p className="mt-1 text-[13px] text-[var(--text-secondary)]">
              Bu bilgiler yalnızca bu cihazda saklanır.
            </p>
          </div>

          <div className="space-y-4">
            <Field label="İsim (isteğe bağlı)">
              <input
                type="text"
                value={displayName}
                onChange={(e) => setDisplayName(e.target.value)}
                placeholder="Emre"
                className={inputCls}
              />
            </Field>
            <Field label="E-posta">
              <input
                type="email"
                value={email}
                onChange={(e) => { setEmail(e.target.value); setError(""); }}
                placeholder="you@example.com"
                className={inputCls}
              />
            </Field>
            <Field label="Parola">
              <input
                type="password"
                value={password}
                onChange={(e) => { setPassword(e.target.value); setError(""); }}
                placeholder="En az 8 karakter"
                className={inputCls}
                onKeyDown={(e) => e.key === "Enter" && void handleBootstrap()}
              />
            </Field>
            <Field label="Parola tekrar">
              <input
                type="password"
                value={passwordConfirm}
                onChange={(e) => { setPasswordConfirm(e.target.value); setError(""); }}
                placeholder="Aynı parolayı gir"
                className={inputCls}
                onKeyDown={(e) => e.key === "Enter" && void handleBootstrap()}
              />
            </Field>
            {error ? <div className="text-[12px] text-[var(--state-warning)]">{error}</div> : null}
          </div>

          <div className="flex gap-3">
            <Button variant="secondary" onClick={() => setStep("welcome")}>
              ← Geri
            </Button>
            <Button variant="primary" onClick={() => void handleBootstrap()} disabled={loading}>
              {loading ? "Oluşturuluyor…" : "Hesap oluştur →"}
            </Button>
          </div>
        </div>
      </Surface>
    </div>
  );
}

const inputCls =
  "h-[50px] w-full rounded-[18px] border border-[var(--border-subtle)] bg-[color-mix(in_srgb,var(--bg-surface)_94%,var(--bg-surface-raised))] px-4 text-[15px] text-[var(--text-primary)] outline-none transition focus:border-[var(--border-focus)]";

function Field({ label, children }: { label: string; children: ReactNode }) {
  return (
    <div className="space-y-1.5">
      <label className="block text-[11px] uppercase tracking-[0.16em] text-[var(--text-tertiary)]">{label}</label>
      {children}
    </div>
  );
}
