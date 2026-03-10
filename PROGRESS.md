# ELYAN PROGRESS

Bu dosya Elyan'in guncel urun ilerleme kaydidir.
Amac: nelerin tamamlandigini, neyin kilitlendigini ve bundan sonra neyin yapilacagini net tutmaktir.

Son guncelleme: 2026-03-09
Durum: Release Candidate
Strateji: shipping first, benchmark-gated maintenance only

---

## 1) Current Status

Elyan artik deneysel mimari refactor asamasinda degil.
Mevcut durumda release adayi urun seviyesindedir.

Guncel kabul durumu:
- production path locked
- benchmark gate green
- preset workflow pack aktif
- product dashboard aktif
- health endpoint aktif
- onboarding / quickstart aktif
- task report surface aktif

---

## 2) Locked Production Path

Tek kabul edilen yol:

`user request -> LiveOperatorTaskPlanner -> OperatorTaskRuntime -> system/screen/browser execution -> verify -> repair/replan -> completion`

Bu yolun disina cikilmayacak.

Kilitledigimiz alanlar:
- yeni orchestration layer yok
- yeni runtime yok
- yeni executor yok
- duplicate workflow engine yok
- agent.py / pipeline.py buyuk refactor yok
- benchmark bypass yok

---

## 3) Completed Milestones

### 3.1 Reliability Foundation
Tamamlandi:
- ToolResult normalization
- deterministic verifier / repair behavior
- telemetry run-store temeli
- legacy wrapper normalization
- executor normalization
- planner / skill / agent execution normalization

### 3.2 Operator Capability
Tamamlandi:
- V3 screen operator runtime
- DesktopHost live state
- DOM-first browser runtime
- target resolution upgrade
- end-to-end operator scenarios
- resumable operator task runtime
- live operator task planner
- observation-aware replanning

### 3.3 Production Reliability
Tamamlandi:
- production benchmark runner
- bounded retry / bounded replan behavior
- benchmark summary and dashboard artifacts
- benchmark-driven tuning
- exact failure code persistence

### 3.4 Product Surface
Tamamlandi:
- `/product` dashboard surface
- `/healthz` release health surface
- preset workflow launcher
- task report surface
- onboarding / setup surface
- release / quickstart surface
- stable startup and readiness scripts

---

## 4) Benchmark Status

Guncel benchmark sonucu:
- pass count: `20/20`
- average retries: `0.1`
- average replans: `0.5`
- remaining failure codes: `none`

Bu sayilar release gate olarak kabul edilmektedir.

Ana benchmark komutu:
`python scripts/run_production_path_benchmarks.py --min-pass-count 20 --require-perfect`

Release readiness komutu:
`bash scripts/production_ready.sh`

---

## 5) Workflow Coverage

### 5.1 Hero Workflows
Guvenilir kabul edilen hero workflow'ler:
- Telegram-triggered desktop task completion
- Research -> document creation -> file verification
- Login -> continue -> upload

### 5.2 Productized Workflow Pack
Aktif preset workflow'ler:
- Telegram-triggered desktop task completion
- Research -> document creation -> file verification
- Safari / Cursor / Terminal / Finder switching tasks
- Login -> continue -> upload
- Interrupted resume after partial completion

Tum preset workflow'ler ayni production path'i kullanir.

---

## 6) Product Readiness

Su yuzeyler tamamlandi:
- main product dashboard
- readiness summary
- benchmark health summary
- preset workflow cards
- task result / task report paneli
- onboarding / quickstart paneli
- release / health paneli
- stable entrypoint and startup scripts

Beklenen urun entrypoint'leri:
- `/product`
- `/healthz`
- `bash scripts/start_product.sh`

---

## 7) What Is Still Left

Kalan isler teknik altyapi degil, release operasyonudur:
- gercek makinede smoke test
- gercek Telegram baglantisi dogrulamasi
- gercek provider/model baglantisi dogrulamasi
- gercek desktop izinleri dogrulamasi
- gercek browser / Playwright ortam dogrulamasi
- son UX wording polish
- gercek kullanicidan gelen bugfix'ler

Bu asamada yeni capability eklemek veya mimari buyutmek plan disidir.

---

## 8) Current Working Policy

Bundan sonra sadece su tur isler alinacak:
- benchmark regression fix
- real workflow failure fix
- product UX clarity fix
- release/startup/readiness bugfix

Bundan sonra alinmayacak isler:
- speculative architecture
- broad refactor
- yeni layer ekleme
- ikinci execution path acma
- benchmark ile zorunlu olmayan teknik temizlik

Kural:
`yeterince iyi ve guvenilir olani cikar, sonra gelistir`

---

## 9) Release Decision

Mevcut karar:
- Elyan release candidate seviyesinde
- shipping uygundur
- release'i durduracak teknik bir benchmark veya workflow failure yoktur

Release'i durduracak tek seyler:
- benchmark gate fail
- hero workflow fail
- product surface acilmaz hale gelirse
- gercek kullanici bloklayan bug

---

## 10) Next Actions

Sadece bu sira ile ilerlenir:
1. canli ortam smoke test
2. demo run
3. gercek kullanicidan feedback topla
4. sadece bugfix patch cik

Yeni mimari is backlog'a gider, aktif gelisim akimina girmez.

