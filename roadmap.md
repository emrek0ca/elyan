# WIQO Professional Assistant Roadmap

Last update: 2026-02-13

## Vision
Wiqo is not a simple command bot. It must operate as a professional AI assistant that can:
- build websites and software projects
- write and debug code
- generate and refine visual content workflows
- run deep research and produce executive outputs
- create professional documents and presentations
- summarize and synthesize large information
- continuously learn from user workflows and improve over time on the same computer

## Product Principles
- Assistant-first: user intent -> plan -> execution -> verification -> delivery.
- Quality gates: every major output is checked against a quality checklist.
- Cost aware: no unnecessary token usage, adaptive model routing.
- Privacy aware: local-first memory and strict redaction for cloud calls.
- Recoverable: each long task leaves resumable state.

## Capability Matrix (Target)
- Website & App Builder
  - HTML/CSS/JS scaffold, framework templates, deployment guides
  - QA checklist: responsive, accessibility, performance, SEO basics
- Coding Copilot
  - feature implementation, refactor, test generation, bug fixing
  - repository-aware coding with safe command execution
- Visual Workflow
  - prompt design, image pipeline orchestration, asset organization
  - style packs and reusable visual directions
- Research Analyst
  - multi-source research, source reliability scoring, synthesis
  - executive + technical report generation
- Documentation Studio
  - professional DOCX/PDF/Markdown output templates
  - audit trail, references, revision history
- Summarization & Knowledge Compression
  - long context compression, task-specific summaries
  - actionable output formats (briefing, checklist, decision memo)

## Architecture Roadmap
1. Intent & Capability Routing (Phase 1)
- Add capability router for high-level domains:
  - website, code, image, research, document, summarization
- Feed routing signals into task decomposition prompts.
- Add domain-specific quality checklist hints.

2. Professional Pipeline Layer (Phase 2)
- Standard multi-step pipeline:
  - discover -> plan -> execute -> verify -> package output
- Add retry/backoff and resumable task state per pipeline.
- Add failure-mode specific fallback strategies.

3. Artifact Quality Engine (Phase 3)
- Quality scoring for code, docs, and research outputs.
- Auto-run validation checks and attach quality report.
- Introduce "publish-ready" threshold.

4. Continuous Learning v2 (Phase 4)
- Learn preferred formats, project styles, and workflow habits.
- Build local skill memory (what worked / what failed).
- Periodic self-review job with optimization recommendations.

5. Operator UX (Phase 5)
- Capability dashboard in UI:
  - model health, cost, quality score, pipeline history
- One-click modes: Build, Research, Document, Ship.

## Execution Plan (Now -> Next)
## Sprint A (active)
- [x] Create roadmap.md and align architecture to vision.
- [x] Implement capability router foundation in core.
- [x] Integrate routing hints into TaskEngine decomposition context.
- [x] Add domain quality checklists to execution requirements.
- [x] Add minimal telemetry for domain success rates.

## Sprint B
- [x] Add project scaffolder templates for web/code outputs.
- [x] Add "professional document pack" generator (docx+md+summary).
- [x] Add image workflow orchestration hooks and style profiles.

## Sprint C
- [x] Add pipeline resume and long-task state management (foundation).
- [x] Add dashboard panels for quality/cost/performance (initial cards).
- [x] Add regression tests for capability routing and pipeline behavior.

## Success Metrics
- Task completion rate by capability domain.
- First-pass success ratio (no rework needed).
- Average quality score per artifact type.
- Token/cost per successful task.
- User correction frequency and resolution speed.

## Non-Goals (for now)
- Training a fully custom foundation model locally.
- Replacing all external model providers immediately.
- Fully autonomous destructive system operations.


WIQO — Professional Digital Operator Roadmap

Last update: 2026-02-13
Product Class: Actionable AI / Computer Operator

⸻

1. Product Definition

Wiqo bir sohbet botu değildir.
Wiqo’nun amacı cevap üretmek değil iş teslim etmektir.

Tanım:

Wiqo, kullanıcının bilgisayarında çalışan, hedef odaklı görevleri planlayan, yürüten, doğrulayan ve teslim eden profesyonel dijital operatördür.

Çalışma modeli:

Goal → Contract → Plan → Execute → Verify → Deliver → Learn

Bu zincirin tamamı gerçekleşmeden görev tamamlanmış sayılmaz.

⸻

2. Core Behavior Principles

2.1 Deterministic Delivery

Her görev başlamadan önce sistem bir Task Contract üretir.

Task Contract içerir:
	•	hedef çıktı
	•	kalite kriterleri
	•	doğrulama yöntemi
	•	başarısızlık koşulları
	•	retry stratejisi
	•	güvenlik seviyesi

Görev Contract karşılanmadan tamamlanmış sayılmaz.

⸻

2.2 Recoverable Execution

Her uzun görev:
	•	checkpoint bırakır
	•	yeniden başlatılabilir
	•	kısmi çıktı üretir
	•	hata sonrası kaldığı yerden devam eder

⸻

2.3 Assistant → Operator Continuum

Wiqo farklı otonomi seviyelerinde çalışır:

Level	Davranış
Advisory	sadece önerir
Assisted	komutla yapar
Confirmed	yapmadan önce onay ister
Trusted	güvenli işlemleri otomatik yapar
Operator	workflow’ları kendi başlatır

Kullanıcı her görev için mod seçebilir.

⸻

2.4 Cost & Privacy Aware Intelligence
	•	Önce yerel akıl yürütme
	•	Gerekirse bulut model
	•	Hassas veri otomatik redaction
	•	Model routing maliyet optimizasyonu

⸻

3. Capability Domains (Not Features — Work Classes)

3.1 Software Production

Teslimat türü: Working Project Pack

İçerik:
	•	kod
	•	test
	•	run guide
	•	deploy guide
	•	kalite raporu

Doğrulama:
	•	çalıştırılabilir
	•	hata yok
	•	bağımlılıklar çözülmüş

⸻

3.2 Research & Analysis

Teslimat türü: Decision Brief

İçerik:
	•	kaynak analizi
	•	çelişki değerlendirme
	•	risk notları
	•	executive summary
	•	teknik ek

Doğrulama:
	•	≥3 güvenilir kaynak
	•	güven skoru hesaplanmış
	•	varsayımlar belirtilmiş

⸻

3.3 Visual & Content Production

Teslimat türü: Production Asset Pack

İçerik:
	•	prompt zinciri
	•	stil yönergesi
	•	varyasyonlar
	•	tekrar üretilebilir pipeline

Doğrulama:
	•	stil tutarlılığı
	•	yeniden üretilebilirlik
	•	marka uyumu

⸻

3.4 Documentation & Communication

Teslimat türü: Professional Document Kit

İçerik:
	•	ana belge
	•	kısa versiyon
	•	sunum özeti
	•	revizyon geçmişi

⸻

3.5 Knowledge Compression

Teslimat türü: Actionable Summary

İçerik:
	•	karar maddeleri
	•	yapılacaklar listesi
	•	riskler
	•	belirsizlikler

⸻

4. Execution Architecture

4.1 Goal Graph Routing

Intent → çoklu domain workflow grafı

Tek domain seçimi yok
Sistem görev zinciri kurar:

Research → Code → Document → Package

⸻

4.2 Professional Pipeline

discover
contract
plan
execute
verify
package
deliver
learn

Her aşama loglanır.

⸻

4.3 Artifact Quality Engine

Her çıktı otomatik değerlendirilir:
	•	completeness
	•	correctness
	•	reproducibility
	•	usability

Publish-Ready threshold altında çıktı teslim edilmez.

⸻

4.4 Learning System

Wiqo öğrenir:
	•	tercih edilen format
	•	tekrar eden görev dizileri
	•	hata sonrası doğru strateji
	•	kullanıcının tolerans seviyesi

Amaç: görev tahmini yapmak

⸻

5. Operational Safety

5.1 Action Risk Classification

Her işlem risk sınıfına girer:

safe
system
destructive
irreversible

Yüksek riskte onay zorunlu.

⸻

5.2 Verification Layer

Her fiziksel aksiyon doğrulanır:
	•	dosya gerçekten oluştu mu
	•	program gerçekten kapandı mı
	•	site gerçekten açıldı mı

Başarısızsa otomatik yeniden planlama.

⸻

6. Product Phases

Phase 1 — Reliable Executor

Amaç: komutları hatasız yapmak
	•	intent doğruluğu
	•	gerçek sonuç doğrulama
	•	sahte başarı yok

Phase 2 — Deliverable Producer

Amaç: çıktı satılabilir hale gelsin
	•	artifact contracts
	•	kalite raporu
	•	publish-ready teslim

Phase 3 — Workflow Assistant

Amaç: ardışık görevleri anlamak
	•	task zinciri
	•	önerilen sonraki adım

Phase 4 — Digital Employee

Amaç: iş gücü yerine geçmek
	•	plan önerme
	•	süreç yürütme
	•	düzenli işler otomasyonu

⸻

7. Success Metrics

System Metrics
	•	görev başarı oranı
	•	doğrulama geçme oranı
	•	ortalama retry sayısı

User Value Metrics
	•	kullanıcı müdahalesi azalma oranı
	•	tekrar kullanılan çıktı oranı
	•	tamamlanan iş süresi kısalması

Business Metrics
	•	haftalık aktif workflow sayısı
	•	görev başına tasarruf edilen süre
	•	Wiqo ile yapılan iş yüzdesi

⸻

8. Non-Goals (Current Stage)
	•	Tam otonom sistem kontrolü
	•	Yerel foundation model eğitimi
	•	İnsan kararının tamamen kaldırılması

⸻

Son Tanım

Wiqo bir AI asistanı değil.

Wiqo = bilgisayarda çalışan teslimat odaklı dijital çalışan

Başarı ölçütü: cevap kalitesi değil
insanın yapmadığı iş miktarıdır
