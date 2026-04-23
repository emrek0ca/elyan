# Elyan Pricing

Elyan is priced around the actual product layers.

## Local / BYOK

- Lowest-cost serious entry point
- User runs local models or provides their own keys
- Local runtime remains primary
- Hosted credits are not required for the local path
- Best fit for privacy-first, self-hosted, or power-user setups

## Cloud-Assisted

- Monthly subscription
- Includes hosted credits
- Covers Elyan-managed cloud usage and hosted web access
- Intended for users who want `elyan.dev` access and managed billing
- Hosted usage is metered through the shared control plane

## Pro / Builder

- Higher limits
- More credits
- More routing and capability throughput
- Better fit for multi-LLM workflows, heavier retrieval, and repeated hosted jobs

## Team / Business

- Per-seat pricing
- Admin controls
- Team entitlements
- Hosted governance
- Designed for shared billing, policy controls, and org-level usage visibility

## Accounting Rule

- Local usage should stay attractive
- Hosted usage should be metered against real infra cost
- Credits should map to model inference, retrieval, integrations, and evaluation
- Abuse control and rate limiting belong in the shared control plane
- Payment success must unlock entitlements through webhook truth, not optimistic UI state

## Payment Flow

1. User signs in to the hosted surface
2. Hosted plan binding is resolved in the control plane
3. Iyzico initialization creates the actual subscription truth
4. Webhook success activates `hostedAccess` and grants the period credits
5. Usage debits are posted to the ledger with a request id and domain bucket
6. Past due and suspended states close hosted access until the provider truth recovers

## Update Cadence

- Canonical release metadata comes from GitHub Releases
- The CLI reports the installed version, latest release, and update status
- `elyan update` is the primary global update path
- Source checkouts can update with `git pull --ff-only`
- VPS deployments should use a reproducible update script, not ad hoc manual edits

## Implemented Foundation

The codebase already contains the narrow data model for plans, accounts, subscriptions, entitlements, credits, and hosted usage accounting.
That foundation is exposed through the shared control plane and the hosted billing routes.
