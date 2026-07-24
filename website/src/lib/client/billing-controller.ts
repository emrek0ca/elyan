import { backendApi, idempotentBackendApi, messageFor, persistentIdempotencyKey } from './api';

type AnyRecord = Record<string, unknown>;
function byId<T extends HTMLElement>(id: string): T | null { return document.getElementById(id) as T | null; }
function object(value: unknown): AnyRecord { return value && typeof value === 'object' && !Array.isArray(value) ? value as AnyRecord : {}; }
function text(value: unknown): string { return typeof value === 'string' ? value : ''; }
function number(value: unknown): number { const parsed = Number(value); return Number.isFinite(parsed) ? parsed : 0; }

function status(message: string, error = false): void {
  const node = byId('billing-status'); if (!node) return;
  node.textContent = message; node.classList.remove('hidden'); node.classList.toggle('text-red-700', error); node.classList.toggle('text-[var(--color-elyan-success)]', !error);
}

function money(value: unknown, currency: unknown): string {
  return new Intl.NumberFormat('en', { style: 'currency', currency: text(currency) || 'USD' }).format(number(value));
}

function usageRow(label: string, raw: AnyRecord): HTMLElement {
  const limit = number(raw.limit); const used = number(raw.used); const percentage = limit > 0 ? Math.min(100, Math.max(0, used / limit * 100)) : 0;
  const wrapper = document.createElement('div');
  const labels = document.createElement('div'); labels.className = 'flex justify-between text-[13px] mb-2';
  const name = document.createElement('span'); name.className = 'font-medium text-[var(--color-elyan-text)]'; name.textContent = label;
  const count = document.createElement('span'); count.className = 'text-[var(--color-elyan-text-muted)] tabular-nums'; count.textContent = `${used} / ${limit}`; labels.append(name, count);
  const track = document.createElement('div'); track.className = 'h-2 w-full bg-[var(--color-elyan-bg-deep)] rounded-full overflow-hidden';
  const bar = document.createElement('div'); bar.className = 'h-full bg-[var(--color-elyan-primary)] rounded-full'; bar.style.width = `${percentage}%`; track.append(bar); wrapper.append(labels, track); return wrapper;
}

async function startCheckout(planCode: string): Promise<void> {
  const idempotency = persistentIdempotencyKey(`billing:${planCode}`);
  try {
    const result = await backendApi<{ checkout?: AnyRecord }>('billing/checkout/init', {
      method: 'POST', headers: { 'idempotency-key': idempotency.key },
      body: JSON.stringify({ planCode, successUrl: `${location.origin}/app/settings/billing?checkout=success`, cancelUrl: `${location.origin}/app/settings/billing?checkout=cancelled` }),
    });
    const checkout = object(result.checkout); const referenceId = text(checkout.referenceId) || text(checkout.id);
    if (!referenceId) throw new Error('Checkout could not be started.');
    idempotency.clear(); location.assign(`/app/api/billing/checkout/${encodeURIComponent(referenceId)}`);
  } catch (error) { status(messageFor(error), true); }
}

function planCard(plan: AnyRecord, currentCode: string, paid: boolean): HTMLElement {
  const code = text(plan.code); const current = code === currentCode || plan.current === true;
  const card = document.createElement('div'); card.className = 'rounded-xl border border-[var(--color-elyan-outline)] bg-[var(--color-elyan-surface)] p-5';
  const top = document.createElement('div'); top.className = 'flex items-start justify-between gap-4';
  const copy = document.createElement('div'); const title = document.createElement('h3'); title.className = 'text-sm font-semibold'; title.textContent = text(plan.label) || code;
  const description = document.createElement('p'); description.className = 'mt-1 text-xs text-[var(--color-elyan-text-muted)]'; description.textContent = current ? 'Current plan' : (Array.isArray(plan.features) ? plan.features.slice(0, 1).map(text).join('') : ''); copy.append(title, description);
  const price = document.createElement('div'); price.className = 'text-right text-lg font-bodoni tabular-nums'; price.textContent = `${money(plan.monthlyPrice, plan.currencyCode)}/mo`; top.append(copy, price); card.append(top);
  if (!current && ['solo', 'pro'].includes(code)) {
    const button = document.createElement('button'); button.type = 'button'; button.className = 'mt-4 w-full rounded-lg bg-[var(--color-elyan-primary)] px-4 py-2 text-sm font-medium text-white hover:bg-[var(--color-elyan-primary-dark)] disabled:opacity-50'; button.textContent = paid ? `Change to ${text(plan.label)}` : `Choose ${text(plan.label)}`;
    button.addEventListener('click', async () => {
      button.disabled = true;
      try {
        if (paid) { await idempotentBackendApi('billing/subscription/change-plan', `billing:change-plan:${code}`, { method: 'POST', body: JSON.stringify({ planCode: code, effectiveAt: 'next_period' }) }); status('Plan change scheduled.'); await loadBilling(); }
        else await startCheckout(code);
      } catch (error) { status(messageFor(error), true); } finally { button.disabled = false; }
    }); card.append(button);
  }
  return card;
}

async function loadBilling(): Promise<void> {
  const [summaryResult, plansResult, profileResult] = await Promise.all([
    backendApi<{ billing?: AnyRecord }>('billing/summary'), backendApi<{ plans?: AnyRecord[]; currentPlanCode?: string }>('billing/plans'), backendApi<{ profile?: AnyRecord }>('billing/profile'),
  ]);
  const billing = object(summaryResult.billing); const billingState = object(billing.billingState); const planState = object(billingState.plan); const usage = object(billingState.usage);
  const currentCode = text(planState.code) || text(plansResult.currentPlanCode) || text(object(billing.subscription).planCode) || 'free';
  const plans = Array.isArray(plansResult.plans) ? plansResult.plans : [];
  const current = plans.find((plan) => text(plan.code) === currentCode) || object(billing.plan);
  const paid = currentCode !== 'free';
  const title = byId('current-plan-title'); if (title) title.textContent = `Elyan ${text(current.label) || currentCode}`;
  const detail = byId('current-plan-detail'); if (detail) detail.textContent = `${text(planState.status) || 'active'} · ${text(planState.source) || text(object(billing.subscription).billingProvider) || 'Elyan billing'}`;
  const price = byId('current-plan-price'); if (price) price.textContent = `${money(current.monthlyPrice, current.currencyCode)}/mo`;
  const usageList = byId('billing-usage'); if (usageList) usageList.replaceChildren(usageRow('AI Tokens', object(usage.tokens)), usageRow('Cloud Tasks', object(usage.tasks)), usageRow('Image Generation', object(usage.imageGeneration)));
  const plansList = byId('billing-plans'); if (plansList) plansList.replaceChildren(...plans.map((plan) => planCard(object(plan), currentCode, paid)));
  const trial = object(billingState.welcomePro); const trialButton = byId<HTMLButtonElement>('claim-trial');
  if (trialButton) trialButton.classList.toggle('hidden', trial.eligible !== true);
  const cancel = byId<HTMLButtonElement>('cancel-subscription'); if (cancel) cancel.classList.toggle('hidden', !paid || object(billingState.actions).canCancel === false);

  const profile = object(object(profileResult.profile).profile); const form = byId<HTMLFormElement>('billing-profile-form');
  if (form) for (const input of form.elements) if (input instanceof HTMLInputElement && text(profile[input.name])) input.value = text(profile[input.name]);
}

export async function initBilling(): Promise<void> {
  const checkout = new URL(location.href).searchParams.get('checkout'); if (checkout === 'success') status('Payment completed. Billing truth is refreshing.'); if (checkout === 'cancelled') status('Checkout was cancelled.', true);
  byId('claim-trial')?.addEventListener('click', async (event) => { const button = event.currentTarget as HTMLButtonElement; button.disabled = true; try { await idempotentBackendApi('billing/trials/pro/claim', 'billing:trial:pro', { method: 'POST', body: '{}' }); status('Pro trial activated.'); await loadBilling(); } catch (error) { status(messageFor(error), true); } finally { button.disabled = false; } });
  byId('cancel-subscription')?.addEventListener('click', async (event) => { if (!confirm('Cancel the subscription at the end of the current period?')) return; const button = event.currentTarget as HTMLButtonElement; button.disabled = true; try { await idempotentBackendApi('billing/subscription/cancel', 'billing:subscription:cancel', { method: 'POST', body: '{}' }); status('Subscription cancellation scheduled.'); await loadBilling(); } catch (error) { status(messageFor(error), true); } finally { button.disabled = false; } });
  const profile = byId<HTMLFormElement>('billing-profile-form'); profile?.addEventListener('submit', async (event) => { event.preventDefault(); const button = profile.querySelector<HTMLButtonElement>('button[type="submit"]'); if (button) button.disabled = true; try { const values = Object.fromEntries(new FormData(profile).entries()); await backendApi('billing/profile', { method: 'PUT', body: JSON.stringify(values) }); status('Billing profile saved.'); } catch (error) { status(messageFor(error), true); } finally { if (button) button.disabled = false; } });
  try { await loadBilling(); } catch (error) { status(messageFor(error), true); }
}
