# PROGRESS.md — Core Runtime Boundary Program

**Latest Session**: 2026-03-29  
**Date**: 2026-03-29  
**Status**: cowork-first desktop korunuyor; event-sourced core runtime, mediator orchestration ve zero-trust boundary programi aktif

---

## Program Summary

### Stabilized Foundations
- Cowork-first desktop shell calisiyor
- Workspace billing ve connector platform zemini mevcut
- Runtime DB, workflow ve telemetry omurgasi aktif
- Security hardening programi field encryption, session persistence ve prompt firewall ile ilerledi

### Architecture Reset
- Mimari yon artik core/runtime split, event log truth, mediator orchestration ve microkernel plugin boundary ustunde sabitlendi
- Architecture quantum, connascence reduction, ADR ve fitness-function cizgisi resmi roadmap haline getirildi
- UI read model + control surface olarak sabitlendi; hidden business logic'i UI'ya tasima hedefi sonlandi

### Current Runtime Direction
- Run ve session state append-only event truth'a dogru tasiniyor
- Orchestration event-driven ve conflict-aware yone cekiliyor
- Security ve audit runtime'un icine daha derin gomuluyor

---

## Current Session Notes

- `core/action_lock.py` conflict-aware lock modeliyle guclendirildi:
  - `policy_scope`
  - `conflict_key`
  - queued requests
  - stale release
  - auto handoff
  - event history
- `core/multi_agent/orchestrator.py` lifecycle event'leri publish etmeye basladi:
  - `orchestrator.flow_started`
  - `orchestrator.flow_blocked`
  - `orchestrator.phase_started`
  - `orchestrator.plan_parsed`
  - `orchestrator.flow_completed`
  - `orchestrator.flow_failed`
- Gateway runtime status artik lock scope, queue depth ve last conflict sinyallerini expose ediyor.
- Bu degisiklikler mediator orchestration, replayable state ve read-model insasi icin temel operational iskeleti olusturuyor.

- `core/cowork_threads.py` canonical `CoworkThread` modeli ile thread, workspace, run, approval ve artifact truth'unu birlestiriyor.
- `core/workflow/vertical_runner.py` workflow lane'lerini gercek artifact pipeline olarak calistiriyor.
- Gateway resmi cowork API ailesi ve desktop telemetry hattini sagliyor.
- Desktop shell runtime lifecycle, sidecar status ve cowork thread state'ini tek urun yuzeyinde gosterebiliyor.
- Connector platform workspace-owned account, scope, health ve trace gorunurlugunu koruyor.
- Billing katmani workspace-owned entitlement modelini surduruyor.

---

## What Is Explicitly In Progress

### 1. Event-Sourced Run and Session Core
- run/session state truth'unu append-only event log'a cekmek
- snapshot ve replay mekanizmasini canonical hale getirmek
- read model projection'larini event log'dan turetmek

### 2. Mediator Orchestration
- planner / executor / verifier / recovery state gecislerini typed events ile standartlastirmak
- approval, retry ve recovery akisini mediator kontrol duzlemine sabitlemek
- action-lock ile orchestrator arasindaki conflict-resolution yolunu genisletmek

### 3. Fitness Functions
- core/plugin/UI boundary testleri
- destructive action approval gate testleri
- replay determinism ve tenant isolation CI gate'leri

### 4. Zero-Trust Runtime
- deny-by-default authz
- immutable audit trail
- blast-radius ve tenant boundary kurallari
- breakglass modelini kisitli ve yogun loglanan bir emergency path olarak tasimak

---

## Validation Snapshot

- Son oturumda hedefli compile check gecti
- Yeni action-lock/orchestrator degisiklikleri icin hedefli testler gecti
- Cowork/workflow/runtime build zemininde onceki hedefli testler korunuyor

Bu dosya bundan sonra feature listesi degil, architecture progress ve runtime direction kaydi olarak tutulur.
