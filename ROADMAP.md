# ROADMAP.md — Elyan Operator Runtime

**Son Guncelleme**: 2026-03-29  
**Mimari Yonu**: event-sourced core runtime + mediator orchestration + microkernel plugin boundaries  
**Mevcut Durum**: cowork-first desktop korunuyor; core/runtime split, append-only state truth ve conflict-aware orchestration ana eksen oldu  
**Test Durumu**: hedefli compile checks, cowork/workflow testleri ve action-lock/orchestrator testleri geciyor

---

## Genel Durum Ozeti

| Katman | Durum | Notlar |
|--------|-------|--------|
| Cowork Desktop | In Progress | canonical shell korunuyor, UI sade ve read-model odakli ilerliyor |
| Workspace Billing | In Progress | workspace-owned entitlement zemini aktif, production wiring sonraki adim |
| Connector Platform | In Progress | workspace-owned connector accounts ve traces aktif, derin capability setleri sirada |
| Architecture Boundary Program | In Progress | architecture quantum, connascence reduction, ADR ve fitness-function katmani resmilesti |
| Event-Sourced Run/Session Core | In Progress | append-only event truth ve read-model ayrimi canonical yone cekiliyor |
| Mediator Orchestration | In Progress | orchestrator ve action-lock event-driven, conflict-aware hale getiriliyor |
| Security Hardening Program | In Progress | zero-trust, tenant isolation, immutable audit, ingress ve prompt guard aktif gelisim aliyor |
| Health Checks | Stub | implement edilmesi gerekiyor |
| Alerting | Stub | implement edilmesi gerekiyor |

---

## Current Implementation Snapshot

- `apps/desktop` canonical urun yuzeyi olarak korunuyor; Tauri shell managed sidecar ile Python runtime'i baslatabiliyor.
- `core/cowork_threads.py` canonical `CoworkThread` truth'unu tasiyor; thread session/workspace/run/approval/artifact referanslarini tek modelde birlestiriyor.
- `core/workflow/vertical_runner.py` `document`, `presentation` ve `website` lane'lerini gercek artifact pipeline olarak calistiriyor.
- Gateway resmi cowork API ailesini ve telemetry hattini sagliyor; desktop selected thread state'ini eventlerle guncelliyor.
- Connector platform workspace-owned hesap, scope, health ve trace verisini canonical contract ile sunuyor.
- Billing user-local degil, workspace-owned entitlement modeli uzerinden ilerliyor.
- Security programi run payload encryption, session persistence, prompt firewall ve security event timeline ile guclendi.
- `core/action_lock.py` artik `policy_scope`, `conflict_key`, queued requests, stale release, auto-handoff ve event history tasiyan conflict-aware lock modeli kullanir.
- `core/multi_agent/orchestrator.py` artik lifecycle event'leri yazar: `flow_started`, `flow_blocked`, `phase_started`, `plan_parsed`, `flow_completed`, `flow_failed`.
- Gateway status payload'i lock scope, queue depth ve last conflict sinyallerini expose ederek orchestration katmanini daha gozenlenebilir hale getirdi.

---

## Architecture Direction 2026-03

Elyan bundan sonra su cizgiye gore gelistirilir:

### 1. Core Runtime Quantum
- session, run, policy, approval, replay, audit ve orchestration truth'u ayni boundary icinde kalir
- ayni DB truth'unu paylasan bilesenler yapay servis ayrimi ile parcalanmaz

### 2. Plugin Quantum
- filesystem, terminal, browser, connector ve model adapter capability'leri microkernel contract ile buyur
- plugin'ler core state'e dogrudan yazmaz; typed commands ve events ile baglanir

### 3. Workspace Quantum
- tenant, entitlement, learning, sync ve data policy burada sahiplenilir

### 4. UI Quantum
- UI yalnizca read model tuketir ve command surface olur
- runtime truth ve hidden business logic UI icine sizmaz

### 5. Observability Quantum
- immutable audit, telemetry, replay, postmortem ve intelligence surfaces append-only veri modeliyle kurulur

Bu boundary cizgisi ayni zamanda Elyan'da connascence azaltma stratejisidir: timing, hidden algorithm ve implicit value bagimliliklari zayiflatilir; schema ve version bagimliligi acik contract olarak tasinir.

---

## Priority Programs

### Program A — Architecture Boundary and Connascence Reduction
- core/runtime, plugin, workspace, observability ve UI ownership matrisi cikarilir
- timing connascence yalnizca mediator orchestration sinirinda tutulur
- hidden import coupling ve schema drift azaltılır
- paylasilan DB truth'u olan bilesenler ayni architecture quantum icinde ele alinir

### Program B — Event-Sourced Run and Session Core
- run/session state canonical truth olarak append-only event log'a tasinir
- snapshot ve replay mekanizmasi event zincirinden turetilir
- CQRS ile write model ve read model ayrilir
- UI ve dashboard yalnizca materialized read model tuketir

### Program C — Mediator Orchestration
- planner, executor, verifier ve recovery tek kontrol duzleminde calisir
- broker topolojisi telemetry ve low-risk fan-out icin kalir
- approval, retry, verification ve recovery state gecisleri event contract ile kaydedilir

### Program D — Zero-Trust Security and Immutable Audit
- deny-by-default authorization
- least privilege grants
- immutable audit trail
- tenant isolation ve blast-radius compartmentalization
- breakglass yalnizca kisitli ve yogun loglanan yol olarak kalir

### Program E — Microkernel Plugin Platform
- plugin manifest
- capability registry
- permission scope
- risk metadata
- health and rollback metadata

### Program F — ADR and Fitness Functions
- buyuk mimari kararlar ADR ile yazilir
- boundary, replay, policy, tenant isolation ve secret handling kurallari fitness-function testleri ile korunur

---

## Immediate Fixes

### Fix-0: Event-Sourced Canonical State
**Dosyalar**: `core/run_store.py`, `core/events/event_store.py`, run/session read models  
**Hedef**: run/session state'i append-only event truth + snapshot uzerine almak

### Fix-1: `run_store` Duplikasyonu ve Truth Netligi
**Dosyalar**: `core/run_store.py`, run/session projections, testler  
**Hedef**: tek canonical truth ve replay edilebilir state modeli

### Fix-2: Async Lock ve Event Bus Tutarliligi
**Dosyalar**: `core/performance_cache.py`, lock/event subscribers  
**Sorun**: `threading.RLock()` async context ile uyumsuz  
**Cozum**: `asyncio.Lock()` ve event-driven concurrency modeline hizalama

### Fix-3: Async Bridge ve Blocking Paths
**Dosyalar**: `api/http_server.py`, sync/async bridge  
**Hedef**: request handling icinde blocking `asyncio.run()` ve benzeri gecis katmanlarini azaltmak

### Fix-4: Hardcoded Runtime and UI Drift
**Dosyalar**: runtime config helpers, UI runtime consumers  
**Hedef**: UI'nin runtime truth'u varsayimla degil config ve read model ile tuketmesi

---

## Roadmap Phases

### Phase 6.0 — Architecture Boundary Program
- architecture quantum inventory
- connascence reduction rules
- import boundaries
- ADR standardi

### Phase 6.1 — Event-Sourced Run and Session Core
- append-only event log canonical truth olur
- snapshot + replay zinciri stabilize edilir
- run/session read models event log'dan turetilir
- request id ve idempotency zorunlu hale gelir

### Phase 6.2 — Mediator Orchestration and Conflict Resolution
- orchestrator mediator topolojisine sabitlenir
- action-lock global + per-policy scope olarak guclendirilir
- conflict detection, stale release, queue handoff ve recovery event-driven calisir
- planner / executor / verifier / recovery state gecisleri event contract ile yazilir

### Phase 6.3 — Policy Engine 2.0
- policy versioning
- dry-run simulation
- approval workflow
- deny-by-default authorization
- breakglass and high-risk controls

### Phase 6.4 — Immutable Audit and Tenant Isolation
- immutable audit log
- workspace and tenant compartmentalization
- connector trace isolation
- memory/cache/storage boundary checks

### Phase 6.5 — Microkernel Plugin Platform
- plugin manifest and capability registry
- filesystem / terminal / browser / connector plugins
- policy-aware plugin sandbox
- rollback and verification metadata

### Phase 6.6 — Fitness Functions and Reliability Gates
- boundary tests
- replay determinism tests
- policy and approval fitness rules
- secret handling and tenant isolation CI gates

### Phase 6.7 — Intelligence and Operator UX
- postmortem ve bottleneck read models
- operator command center replay/diff surfaces
- minimal home + approvals rail + runtime clarity

---

## Test Strategy

### Hedef Test Piramidi
- Unit: event contracts, lock semantics, policy decisions, plugin manifests
- Integration: orchestrator + event store + run projections
- E2E: cowork thread -> approval -> artifact -> replay

### Kritik Fitness Functions
- core plugin veya UI import edemez
- plugin core internals import edemez
- destructive action approval olmadan calisamaz
- replay ayni event log'dan ayni state'i uretir
- tenant-scoped veri diger tenant'a sizamaz
- secrets plaintext olarak log veya run payload'inda kalamaz

---

## Ozet: Ne Yapilmali, Hangi Sirada

```text
[Simdi]     6.0: architecture quantum ve connascence reduction
[Simdi]     6.1: event-sourced run/session core
[Simdi]     6.2: mediator orchestration + action-lock conflict resolution
[Sonra]     6.3: policy engine 2.0 + dry-run + approval lifecycle
[Sonra]     6.4: immutable audit + tenant isolation
[Sonra]     6.5: microkernel plugin platform
[Sonra]     6.6: fitness functions + CI reliability gates
[Surekli]   desktop/read-model sadelestirme + operator UX polish
```
