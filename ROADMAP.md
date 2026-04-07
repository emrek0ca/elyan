# ROADMAP.md — Elyan Commercialization Execution Roadmap

**Last Updated**: 2026-04-03  
**Primary Direction**: local-first operator runtime + workspace-first commercial control plane  
**Current Active Phase**: Commercialization foundation tamamlandi; bundan sonraki aktif cizgi preservation-first architecture hardening (Phase 0 -> Phase 2) + revenue-critical runtime gaps

## Strategic Direction

Elyan bundan sonra su product line uzerinden ilerler:

1. Workspace-first ownership
2. Iyzico-first payment abstraction
3. Elyan Credits ile immutable usage accounting
4. Admin control plane + local runtime boundary
5. User/workspace/global katmanli learning fabric
6. Replayable commercial, learning ve audit event zinciri

Bu line'a ek olarak su engineering discipline canonicaldir:

7. Mevcut calisan davranisi once koru
8. Replacement yerine wrapper, adapter, verifier ve sidecar ile gelistir
9. Non-trivial runtime degisikliklerini feature flag ile ship et
10. Planner, router, verifier ve memory degisikliklerini shadow mode olmadan enforce etme

## Phase Order

### Phase 0 — Documentation Baseline
- README, roadmap, progress, memory, architecture truth'unu commercialization line ile hizala
- commerce, admin, learning ve ledger design docs ekle
- her implementation slice sonunda docs update zorunlu olsun

### Phase 1 — Canonical Commercial Domain
- tek workspace billing truth
- canonical models: plan, token pack, credit balance, ledger entry, provider transaction, entitlement snapshot
- legacy user quota ve subscription path'lerini compatibility adapter arkasina al

### Phase 2 — Iyzico Provider Abstraction
- `PaymentProvider` interface
- `IyzicoProvider` first implementation
- checkout init, token pack purchase, webhook verification, idempotency, refund/failure mapping

### Phase 3 — Workspace, RBAC, Memberships, Seats
- canonical roles: owner, billing_admin, security_admin, operator, viewer
- invite, accept, role change, seat assignment, seat enforcement
- login-time auto bootstrap kaldir
- explicit setup/bootstrap path zorunlu olsun

### Phase 4 — Admin Control Plane
- workspace overview
- subscriptions
- credit ledger
- token pack purchases
- members and roles
- approval queue
- connector health
- learning policy

### Phase 5 — Continuous Learning Fabric
- user memory
- workspace intelligence
- global aggregate intelligence
- privacy classify, consent gate, feature extraction, reward scoring, contextual bandit, offline eval, shadow/canary promotion

### Phase 6 — Runtime Usage and Credit Debiting
- LLM/tool usage -> commercial ledger
- calibrated estimator for non-provider cost paths
- included credits -> purchased credits -> soft degrade ordering

### Phase 7 — Security Hardening
- real CSRF enforcement
- hosted admin/session hardening
- immutable audit + outbox publishing
- workspace-scoped query enforcement

### Phase 8 — Product Documentation Discipline
- `PROGRESS.md`, `ROADMAP.md`, `memory.md` her faz sonunda guncel tutulur
- architecture delta varsa ilgili konu dokumani da guncellenir

## What Is Already Implemented

- `core/feature_flags.py` ile preservation-first feature flag registry foundation
- `core/observability/trace_context.py` ile canonical request/trace context foundation
- gateway request middleware tarafinda canonical trace headers:
  - `X-Elyan-Trace-Id`
  - `X-Elyan-Request-Id`
  - `X-Elyan-Workspace-Id`
- structured log enrichment artik aktif trace context'i tasiyabiliyor
- `core/execution_guard.py` ile canonical shadow-only execution guard foundation
- workflow, cowork ve task-extraction write path'lerinde seat / credit / limit / dispatch outcome telemetry'si artik `execution_guard_shadow` flag'i altinda gozlemlenebiliyor
- approval engine lifecycle ve verifier engine outcome'lari da ayni shadow guard telemetry line'ina baglandi
- browser, file_ops ve screen_operator capability runtime sonuc'lari da ayni guard hattina baglandi
- filesystem ve terminal capability runtime sonuc'lari da ayni guard hattina baglandi
- post-run billing reconciliation foundation artik var:
  - `GET /api/v1/billing/events`
  - `POST /api/v1/billing/reconcile-usage`
  - immutable refund/debit adjustment flow
  - `billing_usage_id` response link'i
  - reconciliation metadata:
    - `actual_cost_usd`
    - `total_tokens`
    - `reconciled_by`
- automatic pricing->reconcile bridge foundation da geldi:
  - `core/billing/reconciliation_bridge.py`
  - workflow/cowork runtime scope activation
  - pricing tracker -> scoped aggregation
  - dispatch-failure auto-refund
  - auto-apply still feature-flagged and default-off
- `core/billing/commercial_types.py` ile canonical plan ve token pack katalogu
- `core/billing/payment_provider.py` ile provider abstraction
- `core/billing/iyzico_provider.py` ile Iyzico-first checkout/webhook foundation
- `core/billing/workspace_billing.py` ile immutable event + credit ledger + entitlement snapshot tabanli workspace billing flow
- `core/persistence/runtime_db.py` icinde billing events, credit ledger, entitlement snapshots, workspace invites ve membership repository zemini
- `core/gateway/server.py` icinde explicit owner bootstrap ve mutating cookie session requests icin CSRF enforcement
- workspace admin controller foundation, role mutation, invite accept/create ve seat assignment APIs
- owner bootstrap seat assignment ve ilk execution seat gate
- desktop setup cockpit:
  - explicit owner bootstrap screen
  - workspace flight deck
  - mobile intake quick-connect
  - glass-first lightweight shell polish
- desktop control plane:
  - invite create/list
  - role mutation
  - seat assignment
  - plans / token packs / credit ledger
- desktop operator intake:
  - `GET/POST /api/v1/inbox/events`
  - `POST /api/v1/tasks/extract`
  - encrypted inbox persistence
  - deterministic task extraction
  - home screen intake + triage + launch flow
- first runtime credit enforcement:
  - usage estimator
  - preflight authorization
  - 402 insufficient-credit response on revenue-critical operator writes
- connector-fed mobile intake:
  - WhatsApp / Telegram / iMessage / SMS inbound capture
  - workspace-bound channel config
  - canonical inbox/extraction reuse

## Next Critical Steps

1. Phase 0'in kalan kismini tamamlamak:
   import-path audit ve capability inventory
2. `ExecutionGuard` shadow telemetry'sini app/native bridge ve remaining capability wrapper'larina genisletmek
3. Automatic pricing bridge'i daha fazla runtime/provider yoluna yaymak ve safe apply rollout kriterlerini olcmek
4. Invite accept + hosted admin web plane
5. Gmail ve diger connector event ingestion'ini yeni inbox pipeline'ina baglamak
6. Learning fabric event contracts ve promotion pipeline'ini kod seviyesinde cikarmak
7. Tenant isolation ve billing/learning replay testlerini genisletmek

## Open Risks

- `core/agent.py` monolith'i commercialization line icin halen yuksek risk tasiyor.
- `core/gateway/server.py` ve `core/persistence/runtime_db.py` uzerinde invasive refactor yuksek regresyon riski tasir; controller extraction ve adapter yaklasimi korunmalidir.
- Workspace billing foundation geldi; desktop shell bunun bir kismini tuketiyor ama hosted admin ve mutating admin screens henuz eksik.
- Home intake usable ve mobil/message lanes canonical pipeline'a baglandi; ama Gmail ve productivity event ingestion henuz ayni hatta tasinmadi.
- Runtime credits path'i revenue-kritik operator write'larda acildi; pricing bridge foundation geldi ama auto-apply rollout ve provider coverage henuz tamamlanmadi.
- Learning fabric hala design-truth seviyesinde; runtime promotions ve offline eval pipeline'i eksik.
- Eski Stripe route'lari deprecated; frontend ve operator flows yeni route'lara alinmali.
- Feature-flag registry ve shadow rollout disiplini olmadan planner/router/verifier degisiklikleri aktiflestirilmemelidir.
