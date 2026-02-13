# ELYAN Professional Assistant Roadmap

Last update: 2026-02-13

## Vision
Elyan is not a simple command bot. It must operate as a professional AI assistant that can:
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

## Sprint D
- [x] Add artifact quality engine with publish-ready threshold enforcement.
- [x] Attach quality report to pipeline completion and UI dashboard cards.
- [x] Add Continuous Learning v2 skill memory (preferred tools/output/quality focus).
- [x] Add local self-review recommendations for optimization opportunities.
- [x] Add one-click Operator UX modes (Build / Research / Document / Ship).

## Sprint E
- [x] Add multimodal tools foundation (speech-to-text, text-to-speech, visual asset pack).
- [x] Add vision+voice fused workflow (`analyze_and_narrate_image`).
- [x] Add multimodal capability health report for operator diagnostics.
- [x] Extend TaskEngine decomposition catalog and heuristic mapping for multimodal intents.
- [x] Add regression checks for multimodal workflow behavior.
- [x] Add live microphone capture and push-to-talk UI integration.

## Sprint F
- [x] Add goal-graph understanding for complex multi-stage instructions.
- [x] Add deterministic multi-domain workflow fallback (research -> code -> document chains).
- [x] Add operator policy engine (Advisory/Assisted/Confirmed/Trusted/Operator).
- [x] Expose operator mode level in settings UI with live policy explanation.
- [x] Add advanced software project pack generator (web/app/game scaffolds + test/run/deploy docs).
- [x] Add clarification gate for ambiguous commands to improve intent accuracy.
- [x] Add execution plan explainability preview in TaskEngine notifications/results.
- [x] Add complex-plan confirmation gate before execution (toggleable in settings).
- [x] Add goal-graph constraint extraction (format/urgency/deliverable intent) to improve intent fidelity.
- [x] Add regression coverage for goal graph + operator policy + software packs.

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


ELYAN — Professional Digital Operator Roadmap

Last update: 2026-02-13
Product Class: Actionable AI / Computer Operator

⸻

1. Product Definition

Elyan bir sohbet botu değildir.
Elyan’nun amacı cevap üretmek değil iş teslim etmektir.

Tanım:

Elyan, kullanıcının bilgisayarında çalışan, hedef odaklı görevleri planlayan, yürüten, doğrulayan ve teslim eden profesyonel dijital operatördür.

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

Elyan farklı otonomi seviyelerinde çalışır:

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

Elyan öğrenir:
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
	•	Elyan ile yapılan iş yüzdesi

⸻

8. Non-Goals (Current Stage)
	•	Tam otonom sistem kontrolü
	•	Yerel foundation model eğitimi
	•	İnsan kararının tamamen kaldırılması

⸻

Son Tanım

Elyan bir AI asistanı değil.

Elyan = bilgisayarda çalışan teslimat odaklı dijital çalışan

Başarı ölçütü: cevap kalitesi değil
insanın yapmadığı iş miktarıdır







Aşağıdaki özet, diğer oturumda kaldığımız yerden devam etmek için hazırlanmıştır. Bu oturumda Elyan’yu “chat bot”tan “delivery odaklı dijital operatör”e yaklaştıracak çekirdek geliştirmeleri
  yaptık.

  1) Ürün Yönü ve Hedef

  - Elyan’nun davranışı “cevap üretme” yerine “iş teslim etme” modeline çekildi:
      - Goal -> Contract -> Plan -> Execute -> Verify -> Deliver -> Learn
  - Roadmap’e uygun şekilde capability bazlı ve profesyonel pipeline bazlı çalışma mantığı güçlendirildi.

  2) Core Mimari Geliştirmeleri

  - core/goal_graph.py
      - Çok adımlı/çok domain görevleri (research -> code -> document -> package) graf mantığıyla planlama temeli.
  - core/operator_policy.py
      - Otonomi seviyeleri eklendi: Advisory, Assisted, Confirmed, Trusted, Operator.
  - core/task_engine.py
      - Routing sinyalleri + domain quality checklist entegrasyonu.
      - Kompleks görevlerde deterministic workflow fallback.
      - Plan önizleme (explainability) ve plan onay kapısı.
      - Riskli aksiyonlar için explicit approval akışı.
      - Multimodal ve software-pack aksiyon haritaları genişletildi.
      - Resume/uzun görev state yaklaşımı güçlendirildi.
  - core/capability_router.py
      - Website/app/game/prototype gibi domain anahtar kelimeleri genişletildi.

  3) Yeni Araçlar / Workflows

  - tools/multimodal_tools.py
      - Görsel/ses/çoklu modalite altyapı kancaları.
  - tools/pro_workflows.py
      - create_software_project_pack benzeri profesyonel çıktı üreten workflow’lar.
  - tools/__init__.py
      - Yeni tool kayıtları eklendi.

  4) UI / Operatör Deneyimi

  - ui/settings_panel_ui.py
      - Operator Mode ayarları ve politika metinleri.
      - Plan onayı toggle’ı.
  - ui/clean_main_app.py
      - Settings sayfası gerçek paneli yükleyecek şekilde düzeltildi.
      - Kritik async loop bug fix (different loop hatası için):
          - run_coroutine_threadsafe + wrap_future ile worker loop’ta güvenli çalışma.
  - ui/clean_chat_widget.py
      - Push-to-talk, STT, son cevabı seslendirme kontrolleri.

  5) Intent/Komut Anlama Düzeltmeleri (senin verdiğin örnek için kritik)

  - core/intent_parser.py
      - “portfolyo sitesi oluştur html css js ...” gibi website builder niyetleri daha sağlam algılanıyor.
      - Arama tetikleyicisi daha sıkılaştırıldı (\bara\b) böylece yanlışlıkla “kedi resmi açma” gibi geçmiş davranışlara sapmıyor.
      - Website-build niyeti varsa browser-search dalını bypass ediyor.

  6) Telegram + Onay Sistemi Düzeltmeleri (son kritik fix)
  Sorun: Telegram’da “Onayla” denince işlem bazen devam etmiyordu.

  Yapılanlar:

  - handlers/telegram_handler.py
      - Pending onaylar loop-safe çözümleniyor (call_soon_threadsafe).
      - Aynı kullanıcı için eski bekleyen onay varsa temizleniyor (stale request engeli).
      - Onay gönderildi/tıklandı/çözüldü logları eklendi.
      - /cancel de loop-safe şekilde pending onayı kapatıyor.
  - security/approval.py
      - Approval request_id üretimi güçlendirildi:
          - saniye bazlı çakışma riski yerine ms + uuid kullanılıyor.
  - Sonuç:
      - “Onayladım ama yapmıyor” akışındaki ana race/çakışma kaynakları kapatıldı.

  7) Test / Regresyon

  - scripts/regression_capability_pipeline.py kapsamı genişletildi:
      - Routing, pipeline, plan confirm, policy, multimodal, workflow davranışlarını kapsayacak şekilde.
  - Son regresyon koşuları başarılı raporlandı.
  - Son yaptığım Telegram/onay patch’lerinde sözdizimi doğrulaması geçti:
      - python3 -m py_compile handlers/telegram_handler.py security/approval.py

  8) Çalıştırma ve Hızlı Kontrol Komutları
  Temiz başlatma:

  cd /Users/emrekoca/Desktop/bot
  source .venv/bin/activate
  pkill -f "python.*main.py|python.*wiqo.py" 2>/dev/null || true
  python main.py

  Onay akışını canlı izleme:

  tail -f logs/*.log | rg "Approval request sent|Approval button clicked|Approval resolved|approval"

  9) Daha Önce Yaşanan Ortam Sorunları ve Durum

  - python-dotenv, telegram, sentence-transformers eksikliği görüldü.
  - Homebrew Python’da PEP668 nedeniyle global pip bloklandı; .venv kullanımı doğru yol.
  - PyQt cocoa plugin sorunu bir noktada görüldü (venv/PyQt kurulum uyumsuzluğu kaynaklı). Bu, proje kodundan çok runtime ortamı tarafı.

  10) Kalan Açık Noktalar (Next)

  - Telegram onay akışını gerçek senaryo ile bir kez daha uçtan uca test etmek.
  - Ayarlar ekranı görsel güncellemelerinin tamamını kullanıcı beklentisine göre polish etmek.
  - Capability regression testlerini CI’ya bağlamak.
  - Multimodal (vision/audio/speech) üretim kalite kapılarını daha sıkılaştırmak.

