import Link from 'next/link';
import { buildPlanPricingView, controlPlanePlanCatalog } from '@/core/control-plane';

export default function PricingPage() {
  const plans = controlPlanePlanCatalog.map(buildPlanPricingView);

  return (
    <div className="site-page">
      <section className="site-hero site-hero--compact">
        <div className="site-kicker">Pricing</div>
        <h1 className="site-title">Local-first entry. Hosted credits when you need them.</h1>
        <p className="site-lead">
          The hosted control plane bills only hosted work: accounts, subscriptions, credits, and metered usage.
          Local runtime usage stays the primary path.
        </p>
      </section>

      <section className="site-section">
        <div className="site-grid site-grid--two">
          {plans.map((plan) => (
            <article key={plan.id} className="site-card">
              <div className="site-price">{plan.monthlyPriceTRY} TRY</div>
              <div className="site-pills">
                <span>{plan.billingSurface === 'hosted' ? 'Hosted billing' : 'Local only'}</span>
                <span>{plan.monthlyIncludedCredits} credits included</span>
              </div>
              <h2>{plan.title}</h2>
              <p>{plan.summary}</p>
              <p className="panel-copy">{plan.pricingNarrative}</p>

              <div>
                <h3>Usage buckets</h3>
                <ul className="site-list">
                  {Object.entries(plan.usageBuckets).map(([bucket, price]) => (
                    <li key={bucket}>
                      {bucket}: {price} credit/unit
                    </li>
                  ))}
                </ul>
              </div>

              <div>
                <h3>Rate limits</h3>
                <ul className="site-list">
                  <li>{plan.rateLimits.hostedRequestsPerMinute} hosted requests/min</li>
                  <li>{plan.rateLimits.hostedToolCallsPerMinute} hosted tool calls/min</li>
                </ul>
              </div>

              <div>
                <h3>Daily guardrails</h3>
                <ul className="site-list">
                  <li>{plan.dailyLimits.hostedRequestsPerDay} hosted requests/day</li>
                  <li>{plan.dailyLimits.hostedToolActionCallsPerDay} hosted tool/action calls/day</li>
                </ul>
              </div>

              <div>
                <h3>Upgrade triggers</h3>
                <ul className="site-list">
                  {plan.upgradeTriggers.map((trigger) => (
                    <li key={trigger}>{trigger}</li>
                  ))}
                </ul>
              </div>
            </article>
          ))}
        </div>
      </section>

      <section className="site-section">
        <div className="site-grid site-grid--two">
          <article className="site-card">
            <h2>Payment flow</h2>
            <p className="panel-copy">
              Local / BYOK is intentionally frictionless. Hosted plans activate only after account binding and billing
              checkout, then issue credits that are spent against real hosted infra cost. Checkout and webhook delivery
              stay idempotent so duplicate events do not double-grant credits.
            </p>
            <ul className="site-list">
              <li>Local / BYOK: local runtime or user-owned keys, no hosted debit.</li>
              <li>Hosted checkout: plan binding, payment session, webhook activation, and credit grant.</li>
              <li>Usage debit: inference, retrieval, integrations, and evaluation.</li>
              <li>Past due / suspended: hosted usage is disabled until recovery.</li>
            </ul>
          </article>

          <article className="site-card">
            <h2>Update cadence</h2>
            <p className="panel-copy">
              Elyan updates locally with a small number of explicit paths. The control plane does not centralize local
              runtime state, and update metadata stays separate from billing metadata.
            </p>
            <ul className="site-list">
              <li>Source checkout: `git pull --ff-only && npm install && npm run build`.</li>
              <li>npm / global install: `elyan update`.</li>
              <li>Homebrew install: `brew update && brew upgrade elyan`.</li>
              <li>VPS deployment: `./ops/update.sh` and `./ops/deploy-release.sh &lt;version&gt;`.</li>
            </ul>
          </article>
        </div>

        <Link href="/auth" className="site-cta">
          Create hosted account
        </Link>
      </section>
    </div>
  );
}
