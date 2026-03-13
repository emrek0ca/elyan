# ELYAN PROGRAM PLAN

Bu dokuman, mevcut bulgulara gore Elyan'daki kritik problemleri kapatmak ve sistemi multi-LLM calistirabilen, gorevleri parcalayip yurutebilen sub-agent mimarisine gecirmek icin resmi uygulama planidir.

Son guncelleme: 2026-03-10
Durum: Recovery + Rebuild Program
Kapsam: security, platform stabilizasyonu, repo konsolidasyonu, test rehabilitasyonu, multi-LLM sub-agent orkestrasyonu

---

## 1) Program Hedefi

Tek hedef:
- tum kritik guvenlik ve guvenilirlik aciklarini kapatmak
- tek ve tutarli bir kod tabaniyla calisan bir urun yolu olusturmak
- gorevleri parcalayip dependency-aware sekilde calistiran sub-agent altyapisini devreye almak
- birden cok LLM provider/model ile rol bazli calisan bir ekip moduna gecmek

Program sonucu:
- guvenli varsayilanlar
- deterministik test/CI
- tek packaging ve tek entrypoint
- gozlemlenebilir ve dogrulanabilir task execution
- multi-LLM team execution ile daha yuksek tamamlama orani

### 1.1 Urun Pozisyonu ve Seviye Gecisleri

Elyan'in resmi urun pozisyonu:
- ilk urun seviyesi:
  - "Turkiye'den cikan en guvenilir dijital operator"
- sonraki urun seviyesi:
  - "cok ajanli, bilgisayar kullanabilen, gorevleri dogrulayarak tamamlayan profesyonel AI calisma sistemi"
- uzun vadeli hedef:
  - "AGI'ye yaklasan, kendi kendini optimize eden, hafizali otonom is isletim katmani"

Bu seviyeleme neden kritik:
- insanlar "AGI" satin almaz; hata yapmayan, isi tamamlayan ve zaman kazandiran sistem satin alir
- bu nedenle once product-market fit ve guvenilir execution gelir
- ileri zeka/memory/otonomluk katmanlari ancak verify edilen operasyon cekirdegi uzerine kurulur

Mimari karar filtresi:
- bir ozellik once verified task completion oranini artirmiyorsa birinci oncelik degildir
- bir agent davranisi deterministik verify katisini gecemiyorsa production-ready sayilmaz
- otonomluk, izin ve risk sinirlari icinde ve guvenilir execution'dan sonra acilir

KPI oncelik sirasi:
1. verified success rate
2. empty artifact rate
3. hallucinated action rate
4. user correction rate
5. average time to verified completion
6. cost per successful task

---

## 2) Baseline Bulgular (Kapatilacak Problem Haritasi)

Asagidaki maddeler kapanmadan program tamamlanmis sayilmaz:

F1
- Gateway mutasyon endpointlerinde admin auth zorunlu degil.
- CORS cok genis.

F2
- Gateway varsayilan metadata ile approval katmani bypass oluyor.
- `autonomy_mode=full` varsayilan davranis.

F3
- Telegram yan komutlari merkezi auth/rate-limit hattini bypass ediyor.
- `allowed_user_ids` bos oldugunda herkes izinli.

F4
- Tool policy deny/approval kurallari gercek tool adlariyla tam eslesmiyor.
- Runtime/shell execution yolunda fiili acik kapilar var.

F5
- Dosya ve run root pathleri tutarsiz.
- `Path.home()` ve masaustu pathleri dogrudan kullaniliyor.

F6
- Repo iki farkli gercege bolunmus: kok + `bot/` aynasi.
- Packaging/version/entrypoint tutarsiz.

F7
- Test discovery bozuk.
- `tests/` ile `bot/tests/` modullerinde import mismatch var.

F8
- Bazi komut yollarinda kirik import/refactor kalintisi var.
- Ornek: `ollama_helper` syntax, `voice_manager` import, `core.llm.factory` fallback.

F9
- Hybrid model routing ve capability routing siralamasi tutarsiz.
- `code` vs `coding` domain uyumsuzlugu.

F10
- Contract/verify asamasi gercek artifact yerine stub payload dogruluyor.

F11
- `DesktopHost` state global ve user/session izole degil.

---

## 3) Hedef Mimari (Program Sonu)

Tek kabul edilen hedef yapi:

`request -> secure intake -> intent/capability parse -> task decomposition (DAG) -> sub-agent team scheduling -> multi-LLM execution -> verify/repair -> evidence-backed delivery`

### 3.1 Control Plane
- Tek gateway auth modeli
- Tek runtime policy resolver
- Tek execution orchestration path
- Session/user scoped state

### 3.2 Execution Plane
- Gorevler `TaskSpec` uzerinden standartlasmis alt gorevlere bolunur.
- Alt gorevler dependency graph ile siralanir.
- Her alt gorev uygun sub-agent role'una atanir.
- Her sub-agent sadece izinli tool scope ile calisir.

### 3.3 Model Plane (Multi-LLM)
- Router modeli
- Planner modeli
- Worker modelleri
- Critic modeli
- Verifier modeli
- Provider fallback ve collaboration pool

### 3.4 Verification Plane
- Output contract gercek payload/artifact uzerinden calisir.
- Evidence gate artifacts + logs + run ledger uzerinden karar verir.
- Repair/retry bounded policy ile uygulanir.

### 3.5 Security Plane
- Default deny
- Explicit allow + role scoped tools
- Interactive approval risk seviyesine gore zorunlu
- Channel bazli auth/rate-limit zorunlu

---

## 4) Multi-LLM Sub-Agent Tasarimi

### 4.1 Sub-Agent Roller
- `lead_planner`: gorevi parcala, DAG cikar.
- `research_worker`: kaynak toplama/sentez.
- `code_worker`: kod/patch/implementasyon.
- `operator_worker`: screen/browser/system aksiyonlari.
- `critic`: kalite, risk, tutarlilik denetimi.
- `verifier`: artifact ve contract gate kontrolu.

### 4.2 Model Esleme
- `router`: ucuz/hizli model, yuksek throughput.
- `lead_planner`: guclu reasoning model.
- `research_worker`: guclu context window model.
- `code_worker`: kod performansi yuksek model.
- `critic/verifier`: tutarlilik ve guardrail odakli model.

### 4.3 Gorev Parcala Kurali
- Her user istegi once `objective`, `constraints`, `deliverables` alanlarina ayrilir.
- En az bir `done_criteria` tanimlanir.
- Gorevler `id`, `action`, `params`, `depends_on`, `success_criteria` ile normalize edilir.

### 4.4 Scheduler Kurali
- Dependency saglanmadan task calismaz.
- Paralel calisma sadece bagimsiz dugumlerde acilir.
- Her dugum icin timeout, retry budget, fail-fast siniri vardir.

### 4.5 Team Execution Contract
- Her sub-agent su sekilde sonuc doner:
- `status`
- `artifacts`
- `logs`
- `verification_hints`
- `cost_usage`
- Lead only branch/merge kararini verir.

---

## 5) Faz Bazli Uygulama Plani

## P0 - Security Lockdown (acil, gun 1-3)

Hedef:
- Yetkisiz kontrol yuzeyini kapatmak.
- Approval bypass hatlarini kapatmak.

Isler:
- Gateway mutasyon endpointlerine zorunlu admin auth ekle.
- `/api/message` icin admin auth veya signed channel auth zorunlulugu getir.
- CORS allowlist modeline gec.
- Router tarafinda varsayilan `autonomy_mode=full` davranisini kaldir.
- `interactive_approval` varsayilanini guvenli moda cek.
- Telegram extension komutlarinda da `check_user` + rate limiter zorunlu hale getir.
- Tool policy'yi default deny + explicit allow modeline cek.

Cikis kriteri:
- Guvenlik testleri yesil.
- Yetkisiz request ile config/model/channel degisikligi yapilamiyor.

---

## P1 - Repo ve Packaging Konsolidasyonu (gun 2-5)

Hedef:
- Tek kaynak kod gercegi.
- Tek entrypoint ve tek versiyon dogrusu.

Isler:
- Kok proje canonical kaynak olarak sabitlenir.
- `bot/` aynasi arsivlenir veya test discovery disina kesin cikarilir.
- `pyproject.toml`, `setup.py`, runtime version kaynaklari teklestirilir.
- Tek CLI entrypoint politikasi belirlenir ve tum script/test buna baglanir.
- Kirik import/fallback kalintilari temizlenir.

Cikis kriteri:
- Packaging metadata tutarli.
- `elyan version` ve package version tek deger donuyor.

---

## P2 - Test Rehabilitasyonu (gun 3-7)

Hedef:
- Deterministik test discovery.
- CI'da tekrar edilebilir stabil sonuc.

Isler:
- `pytest.ini` icinde `testpaths` ve `norecursedirs` duzgun tanimlanir.
- `bot/tests` ve test disi scriptlerin discovery'ye girmesi engellenir.
- Mevcut 11 unit failure'in kok nedenleri kapatilir.
- Sandbox path kaynakli testler storage resolver uzerinden stabilize edilir.
- Yeni regression testleri eklenir.

Cikis kriteri:
- `pytest --collect-only` hatasiz.
- Unit suite belirlenen baseline'da yesil.

---

## P3 - Storage ve Runtime Path Birligi (gun 5-8)

Hedef:
- Tum runtime dosya yollarinda tek resolver.

Isler:
- `Path.home()` kullanan calisma pathleri `core/storage_paths.py` ile degistirilir.
- Sub-agent workspace root resolver uzerinden uretilir.
- Routine report ve benzeri out pathler resolver tabanli olur.
- Channel/file upload pathleri validate/sanitize pipeline'dan gecirilir.

Cikis kriteri:
- Read-only/sandbox ortamlarda deterministic fallback calisir.
- Runtime dosya yazma hatalari minimize edilir.

---

## P4 - Sub-Agent Team Core (gun 7-12)

Hedef:
- Gorevleri parcali ve role-based calistiran cekirdek.

Isler:
- `core/sub_agent` altyapisi team execution contract ile genisletilir.
- Team planner -> scheduler -> worker -> critic -> verifier zinciri netlestirilir.
- Session state user/request scope ile izole edilir.
- Tool scope enforcement sub-agent seviyesinde zorunlu hale getirilir.

Cikis kriteri:
- En az 3 farkli role ile bir DAG gorevi sorunsuz tamamlanir.
- Dependency ihlali olmadan paralel calisma gerceklesir.

---

## P5 - Multi-LLM Orchestration (gun 9-15)

Hedef:
- Her role icin uygun model secimi ve fallback.

Isler:
- Model orchestrator role map'i netlestirilir.
- `code` vs `coding` domain uyumu duzeltilir.
- Capability routing ve hybrid routing sirasi duzeltilir.
- Collaboration pool secimi policy tabanli hale getirilir.
- LLM client fallback ve collaboration check defensive olarak sertlestirilir.

Cikis kriteri:
- Research/code/operator gorevlerinde role-model secimi beklenen sekilde calisiyor.
- Provider arizalarinda kontrollu fallback var.

---

## P6 - Task Decomposition + DAG Scheduling (gun 12-18)

Hedef:
- Her karmasik istek parcali ve izlenebilir gorevlere ayrilsin.

Isler:
- Intent/capability/goal graph ciktilarindan normalize `TaskSpec` olustur.
- DAG validator ekle.
- Scheduler'da retry policy, timeout policy, fail-fast policy tanimla.
- Execution ledger'da node-level evidence kaydi zorunlu hale getir.

Cikis kriteri:
- Karma gorevler deterministic plan + DAG ile calisiyor.
- Her node icin evidence ve status kaydi var.

---

## P7 - Verify/Contract Hardening (gun 15-20)

Hedef:
- Contract dogrulamasi gercek artifact uzerinden calissin.

Isler:
- Verify payload'i schema required alanlariyla doldur.
- `required_outputs`, `quality_gates`, `verify` alanlarini gercek sonucla map et.
- Stub contract hatalarini kaldir.
- Gate failures icin repair/retry politikasini standardize et.

Cikis kriteri:
- False-negative contract hatalari kalkar.
- Verify pass/fail karari artifact kanitina dayanir.

---

## P8 - Stabilizasyon ve Rollout (gun 20+)

Hedef:
- Program ciktilarini kontrollu sekilde uretime almak.

Isler:
- Feature flags ile asamali rollout.
- Benchmark ve workflow pack regression kosulari.
- Telemetry dashboard'da yeni metrikler.
- Incident runbook guncellemesi.

Cikis kriteri:
- Production gate yesil.
- Rollback plani test edilmis.

---

## 6) Bilesen Bazli Uygulama Listesi

Security ve Gateway:
- `core/gateway/server.py`
- `core/gateway/router.py`
- `core/agent.py`
- `security/tool_policy.py`
- `security/validator.py`
- `handlers/telegram_handler.py`
- `handlers/telegram_extensions.py`

Platform ve Runtime:
- `core/storage_paths.py`
- `core/sub_agent/manager.py`
- `core/sub_agent/team.py`
- `core/runtime/hosts/desktop_host.py`
- `core/scheduler/routine_engine.py`

Model ve Planning:
- `core/model_orchestrator.py`
- `core/llm_client.py`
- `core/pipeline.py`
- `core/hybrid_model_policy.py`
- `core/capability_router.py`
- `core/intent_parser/*`

Verify ve Contract:
- `core/pipeline_upgrade/contracts.py`
- `contracts/*.schema.json`
- `core/verifier/*`
- `core/evidence/*`

Packaging ve Test:
- `pyproject.toml`
- `setup.py`
- `cli/main.py`
- `pytest.ini`
- `tests/*`

---

## 7) Test ve Gate Plani

Her faz sonunda zorunlu gate:
- static: `python -m compileall core tools cli config security handlers capabilities ui`
- collect: `python -m pytest --collect-only -q`
- unit: `python -m pytest tests/unit -q`
- integration: `python -m pytest tests/integration -q`
- e2e smoke: `python -m pytest tests/e2e -q -k smoke`

Program sonu minimum quality hedefleri:
- collect errors: `0`
- critical security tests: `100% pass`
- unit pass rate: `>= 98%`
- benchmark pass count: `100%`

---

## 8) Operasyon Metrikleri

Takip edilecek metrikler:
- task completion rate
- first-pass success rate
- average retries per task
- average replans per task
- approval bypass incident count
- unauthorized endpoint mutation attempts
- model fallback frequency
- per-role token/cost usage
- verify gate fail distribution

---

## 9) Risk Kaydi ve Azaltim

R1
- Risk: Buyuk refactor sirasinda yeni regressions.
- Azaltim: phase gate + feature flag rollout.

R2
- Risk: Security kapanislari mevcut UX'i kirabilir.
- Azaltim: channel bazli gecis ve fallback mesajlari.

R3
- Risk: Multi-LLM maliyeti kontrol disina cikabilir.
- Azaltim: per-role budget cap + adaptive routing.

R4
- Risk: Sub-agent paralellik race condition uretir.
- Azaltim: dependency lock + deterministic scheduler.

R5
- Risk: `bot/` aynasi kaldikca tekrar drift olur.
- Azaltim: canonical source policy + CI guard.

---

## 10) Definition of Done (Tum Problemler Kapandi)

Program ancak su kosullar saglaninca tamamlanir:
- F1-F11 maddeleri kapanmis ve testle dogrulanmis olacak.
- Tek kaynak kod gercegi ve tek packaging gercegi olacak.
- Test discovery tam temiz olacak.
- Security default'lari guvenli olacak.
- Multi-LLM sub-agent team mode production path icinde aktif olacak.
- Gorev parcalama + DAG + verification + evidence zinciri uc uca calisacak.
- Rollout, rollback ve runbook dokumanlari guncel olacak.

---

## 11) Uygulama Disiplini

Kurallar:
- Her PR bir faz hedefiyle iliskilendirilecek.
- Her PR'da test kaniti zorunlu olacak.
- Faz disi ozellik ekleme kabul edilmeyecek.
- Guvenlik bypass eden gecici cozum eklenmeyecek.
- Yeni davranislar feature flag arkasinda acilacak.

---

## 12) Ilk 72 Saatlik Uygulama Plani

Gun 1:
- P0 gateway auth + CORS lockdown
- P0 autonomy/approval default duzeltmeleri
- P0 telegram extension auth-rate limit kilitleri

Gun 2:
- P1 packaging/version/entrypoint tekilleme
- P2 pytest discovery rehabilitasyonu
- Kirik import/refactor kalintilarinin kapatilmasi

Gun 3:
- P3 storage path birligi
- P2 failing unit test kapanislari
- P4 sub-agent team contract taslagi ve ilk working path

---

## 13) Not

Bu dokuman plan dokumanidir.
Her faz tamamlandiginda ilgili bolumde durum notu ve test kaniti eklenir.
Program boyunca hedef, "hizli degisiklik" degil, "dogrulanmis ve geri alinabilir degisiklik"tir.

---

## 14) Durum Notu (2026-03-10)

### 14.1 Kapatilan Bulgular (P0 ilerleme)

F1 (Gateway auth + CORS):
- `core/gateway/server.py` uzerinde `/api/message`, tum mutating `/api/*` endpointleri ve hassas read endpointleri admin auth ile korunuyor.
- CORS wildcard modeli kaldirildi; loopback/config allowlist disi origin 403 donuyor.

F2 (Autonomy/approval varsayilanlari):
- `core/gateway/router.py` varsayilan `autonomy_mode` `balanced` oldu.
- `core/agent.py` non-interactive kanalda approval gereken aksiyonlari auto-approve etmiyor; `APPROVAL_REQUIRED` ile bloke ediyor ve audit izi birakiyor.

F3 (Telegram auth/rate-limit bypass):
- `handlers/telegram_handler.py` icinde `allowed_user_ids` bosken default deny aktif.
- Geri uyumluluk icin yalnizca explicit flag (`ELYAN_TELEGRAM_ALLOW_PUBLIC` veya `telegram_allow_public`) ile public mode aciliyor.
- `setup_handlers` icinde komutlar, extension komutlari, routine/proactive komutlari, browser komutlari, voice/photo/document/vision handler'lari merkezi auth + rate-limit sarmalamasina alindi.
- Callback/message contextlerinde deny/rate-limit bildirimleri guvenli sekilde iletiliyor.

F4 (Tool policy eslesme acigi):
- `security/tool_policy.py` deny/allow/approval kurallari pattern-aware hale getirildi.
- `exec` gibi policy girdileri artik `execute_shell_command` gibi gercek tool adlarina eslesiyor.
- `tools.default_deny` / `security.toolPolicy.defaultDeny` bayraklari ile strict default-deny modu devreye alindi (varsayilan: acik).
- Dashboard policy hesaplamasi `tool_policy` engine ile birebir ayni karar modeline hizalandi.

F7 (Test discovery) - partial:
- `pytest.ini` icinde `testpaths=tests` ve `norecursedirs` tanimlandi (`bot/` aynasi ve runtime output dizinleri dislandi).
- `python -m pytest --collect-only -q` kosusunda collect hatasi yok; `937 tests collected`.

F6 (Packaging/version/entrypoint) - partial:
- Ortak versiyon kaynagi `core/version.py` ile teklestirildi; CLI/config/domain/gateway fallback bu kaynaga baglandi.
- `pyproject.toml` metadata `name=elyan`, `dynamic version (core.version.__version__)`, `elyan=elyan_entrypoint:main` ile normalize edildi.
- `setup.py` versiyon kaynagi `APP_VERSION` ve console entrypoint `elyan_entrypoint:main` ile pyproject ile hizalandi.

F5/F11 (Path ve workspace izolasyonu) - partial:
- `core/sub_agent/manager.py` sub-agent workspace root'unu sabit `~/.elyan/subagents` yerine `resolve_elyan_data_dir()/subagents` uzerinden cozecek sekilde guncellendi.
- Bu degisiklikle sandbox/read-only ortamlarda sub-agent testlerinde gorulen permission hatalari kapatildi.
- `core/scheduler/routine_engine.py` deterministic excel/summary cikti pathleri `ROUTINE_REPORT_DIR` + temp fallback kullanacak sekilde guvenli hale getirildi (Desktop hardcode kaldirildi).

F9/F8 (Model routing ve LLM orkestrasyon stabilitesi) - partial:
- `core/model_orchestrator.py` aday siralamada role-enforced registry filtreleri ve configure/provider fallback davranisi sertlestirildi.
- `get_best_available(inference)` fallback akisi router yoksa `active_provider` oncelikli davranacak sekilde duzeltildi.
- `core/llm_client.py` collaboration config okumasi orchestrator mocklarinda method yoksa hata vermeyecek defensive fallback ile guncellendi.

Intent parser/routine regression kapanisi:
- `core/intent_parser/_apps.py` icinde \"browser ac + arastirma\" pattern'i `open_url` yerine `research` gorevine ayrilarak multi-task beklenen davranisa getirildi.
- `tests/unit/test_smart_approval.py` yeni interaktif onay politikasi ve auxiliary proof tool cagrisini yansitacak sekilde guncellendi.

### 14.2 Test Kaniti

Asagidaki regresyon kosulari yesil:
- `pytest -q tests/test_telegram_approval_flow.py tests/unit/test_gateway_server_message.py tests/unit/test_gateway_router.py tests/unit/test_agent_intervention.py tests/unit/test_agent_execute_tool_normalization.py` -> `53 passed`
- `pytest -q tests/unit/test_tool_policy.py tests/unit/test_runtime_policy.py tests/unit/test_gateway_server_message.py tests/test_telegram_approval_flow.py` -> `25 passed`
- `pytest -q tests/unit/test_tool_policy.py tests/unit/test_gateway_tools_helpers.py tests/unit/test_gateway_server_message.py tests/unit/test_gateway_router.py` -> `62 passed`
- `pytest -q tests/test_telegram_approval_flow.py tests/unit/test_agent_intervention.py tests/unit/test_agent_execute_tool_normalization.py tests/unit/test_runtime_policy.py` -> `17 passed`
- `python -m pytest --collect-only -q` -> `937 tests collected`
- `pytest -q tests/unit/test_packaging_metadata.py tests/unit/test_cli_main.py tests/unit/test_gateway_tools_helpers.py tests/unit/test_tool_policy.py tests/unit/test_gateway_router.py` -> `58 passed`
- `pytest -q tests/unit/test_agent_team_scheduler.py tests/unit/test_sub_agent_manager.py tests/unit/test_hybrid_model_policy.py tests/unit/test_model_routing_consistency.py tests/unit/test_llm_local_first_policy.py tests/unit/test_intent_parser_and_dashboard.py::test_open_and_research_without_connector_still_multi_task tests/unit/test_routine_engine.py::test_run_routine_deterministic_tools tests/unit/test_smart_approval.py` -> `23 passed`
- `pytest -q tests/unit` -> `816 passed, 6 skipped`

### 14.3 Acik Noktalar (P0->P1 gecis oncesi)

- P1/P2 kapsamindaki repo/package/test-discovery konsolidasyonu devam ediyor.

### 14.4 Son Gelisimler (2026-03-10, gec update)

P3 (Storage ve Runtime Path Birligi) ilerlemesi:
- `core/runtime/benchmarks.py` varsayilan benchmark root'u `resolve_elyan_data_dir()/runtime_benchmarks` oldu.
- `core/runtime/task_sessions.py` varsayilan task root'u `resolve_elyan_data_dir()/operator_tasks` oldu.
- `core/runtime/scenarios.py` varsayilan scenario artifact root'u `resolve_elyan_data_dir()/operator_scenarios` oldu.
- `core/runtime/emre_workflows.py` varsayilan workflow report root'u ve benchmark summary default source'u resolver tabanina alindi.
- `core/runtime/hosts/desktop_host.py` varsayilan state path'i `resolve_elyan_data_dir()/desktop_host/state.json` oldu.

Regresyon guvencesi:
- Yeni test dosyasi eklendi: `tests/unit/test_runtime_storage_paths.py`
- Bu test runtime default root/path fonksiyonlarinin resolver tabanli oldugunu dogruluyor.

Ek stabilizasyon kapanislari:
- `core/delivery/engine.py` workspace root'u resolver tabanina alindi (sandbox permission fail kapandi).
- `core/cdg_engine.py` dynamic `code_project` planda path hint yoksa fallback output path/content enjekte edilerek bos `node_qa_gates` regressioni kapatildi.
- Browser/screen fallback ve system verification akislarinda false-negative durumlar kapatildi (DOM_UNAVAILABLE -> screen inspect fallback, system step post-observation ile verify uyumu, open idempotent verification yumusatma).

Test kaniti (guncel):
- `pytest -q tests/e2e` -> `45 passed`
- `pytest -q tests/unit tests/integration` -> `840 passed, 6 skipped`
- `pytest -q tests` -> `939 passed, 6 skipped`
- hedefli path/runtime regressions -> `6 passed`

### 14.5 Siradaki Isler (Unutulmamak icin net backlog)

Kisa vade (hemen sonraki sprint):
1. P3 tamamlama: runtime disindaki kalan `Path.home()/.elyan` kullanimlarini (ozellikle gateway upload/tmp, reporting, memory/compliance, scheduler persist pathleri) sistematik olarak resolver tabanina tasimak.
2. P1 tamamlama: tek packaging gercegini commit seviyesinde kilitlemek, `bot/` aynasini CI/test-discovery acisindan tamamen devre disi birakmak.
3. P2 sertlestirme: collect gate'i CI'da zorunlu hale getirmek ve smoke marker setini minimum ama anlamli kapsamla korumak.

Orta vade:
1. P4: sub-agent team contract'ini production path'e zorunlu baglamak (planner->scheduler->worker->critic->verifier).
2. P5: role->model mapping ve fallback davranisini config + test ile harden etmek.
3. P6/P7: DAG/task evidence zincirini her node icin zorunlu ve audit-ready hale getirmek.

Tamamlanma kontrolu:
- Her adimdan sonra `pytest -q tests` yesil kalmali.
- Path birligi adimlarinda mutlaka regression testi eklenmeli.

### 14.6 Son Gelismeler (2026-03-10, gece update 2)

P4/P6 hazirliklari (Agent Module Architecture):
- `core/agents/` altinda module registry tabanli yeni bir yapi eklendi (`core/agents/registry.py`).
- 10 adet stratejik module resmi kataloga alindi:
  - `context_recovery`
  - `automatic_learning_tracker`
  - `invisible_meeting_assistant`
  - `website_change_intelligence`
  - `life_admin_automation`
  - `deep_work_protector`
  - `ai_decision_journal`
  - `personal_knowledge_miner`
  - `project_reality_check`
  - `digital_time_auditor`
- Ilk calisir module'lar:
  - `core/agents/context_recovery.py`
  - `core/agents/website_change_intelligence.py`
  - `core/agents/invisible_meeting_assistant.py`
- Bu module'lar resolver tabanli artifact/report path kullaniyor ve `~/.elyan/reports/...` altina deterministic cikti uretiyor.

Automation scheduler guclendirmesi:
- `core/automation_registry.py` module-aware scheduler olarak genisletildi.
- `module_id` iceren otomasyonlar pipeline yerine dogrudan module runner uzerinden calisiyor.
- Due job'lar semaforlu paralel calisiyor (`ELYAN_AUTOMATION_MAX_PARALLEL`).
- Her kosudan sonra `last_status`, `last_error`, `last_result`, `last_run` persisted oluyor.
- `register_module(...)` API eklendi (module spec + interval + params ile otomasyon kaydi).

CLI ve operasyon:
- `python -m cli.main agents modules` komutu ile module katalogu listelenebilir hale getirildi.
- Gateway start path'inde kritik dogruluk kapanisi:
  - `main.py` icinde gateway start artik `server.start(port=port)` ile gercek verilen porta bind ediyor.
  - `cli/commands/gateway.py` icinde PID dosyasi yalnizca hedef portu dinleyen sureci "running" kabul ediyor.

Regresyon guvencesi (ek):
- Yeni testler:
  - `tests/unit/test_agent_modules.py`
  - `tests/unit/test_automation_registry_modules.py`
  - `tests/unit/test_main_gateway_entrypoint.py`
- Guncellenen testler:
  - `tests/unit/test_cli_command_wrappers.py`
  - `tests/unit/test_gateway_cli.py`
  - `tests/unit/test_gateway_server_message.py`
  - `tests/unit/test_routine_engine.py`
- Son hedefli kanit:
  - `pytest -q tests/unit/test_agent_modules.py tests/unit/test_automation_registry_modules.py tests/unit/test_cli_command_wrappers.py tests/unit/test_cli_main.py tests/unit/test_gateway_cli.py tests/unit/test_routine_engine.py` -> `45 passed`
  - ek gateway/routine/entrypoint regresyon paketi -> `59 passed`

### 14.7 Siradaki Isler (kisa vade net devam)

1. 10 module'un kalan 7 runner'ini (learning tracker, life admin, deep work, decision journal, personal knowledge miner, project reality check, digital time auditor) "planned_only" durumundan cikarmak.
2. Module scheduler'a per-module timeout/retry budget ve circuit-breaker policy eklemek.
3. Dashboard/product home tarafina module saglik ve son kosu ozet kartlari eklemek.
4. P1/P2 tamamlanmasi: repo canonical source + CI collect gate + packaging drift kilitleri.

### 14.8 Son Gelismeler (2026-03-10, gece update 3)

Agent module execution kapsami tamamlandi (10/10 runner aktif):
- Yeni eklenen calisir runner'lar:
  - `core/agents/automatic_learning_tracker.py`
  - `core/agents/life_admin_automation.py`
  - `core/agents/deep_work_protector.py`
  - `core/agents/ai_decision_journal.py`
  - `core/agents/personal_knowledge_miner.py`
  - `core/agents/project_reality_check.py`
  - `core/agents/digital_time_auditor.py`
- `core/agents/registry.py` icinde `_RUNNERS` map'i tum 10 module'u kapsayacak sekilde tamamlandi.
- `core/agents/__init__.py` export listesi yeni module runner'lariyla guncellendi.

Automation persistence race-condition kapanisi (dogruluk iyilestirmesi):
- `core/automation_registry.py` icinde register/update/remove akislari dosya kilidi (`fcntl`) ile atomik read-modify-write modeline cekildi.
- Paralel `module-enable` cagrisinda `automations.json` overwrite ile kayip olusma problemi kapatildi.

Yeni regresyon guvencesi:
- `tests/unit/test_agent_modules.py`
  - tum yeni runner'lar icin execution testi eklendi (`planned_only` regressioni kapandi).
- `tests/unit/test_automation_registry_modules.py`
  - multi-instance register korunumu testi eklendi.
  - stale instance update senaryosunda diger kayitlari koruma testi eklendi.

Canli dogrulama (local run):
- `python -m cli.main gateway health --json --port 18789` -> `healthy: true`
- `python -m cli.main agents modules` -> 10 module katalogda gorunur.
- Tum 10 module icin `run_agent_module(...)` smoke kosusu basarili.
  - 9 module rapor uretimi dogrulandi (`~/.elyan/reports/...`).
  - `invisible_meeting_assistant` transkript olmadiginda beklenen sekilde `no_transcripts` donuyor.
- Paralel 3 adet `module-enable` kosusunda `~/.elyan/automations.json` kayit sayisi beklenen sekilde artarak korunuyor (race fix dogrulandi).

Test kaniti (guncel):
- `python -m pytest -q tests/unit/test_agent_modules.py tests/unit/test_automation_registry_modules.py tests/unit/test_cli_command_wrappers.py tests/unit/test_cli_main.py` -> `31 passed`
- `python -m pytest -q tests/unit/test_gateway_cli.py tests/unit/test_main_gateway_entrypoint.py tests/unit/test_routine_engine.py` -> `26 passed`

Kisa vade net devam:
1. Module scheduler icin per-module timeout/retry budget ve circuit-breaker policy eklemek.
2. Dashboard'da module health + son rapor + son status kartlarini gostermek.
3. Module param schema validation (jsonschema/pydantic-lite) ekleyerek hatali payload'lari scheduler girisinde elemek.

### 14.9 Son Gelismeler (2026-03-10, gece update 4)

Scheduler gorunurluk/dogruluk kapanisi:
- `core/automation_registry.py` icinde `get_active()` artik kilitli disk refresh (`_load_locked`) yapiyor.
- Bu sayede gateway/scheduler prosesi, CLI gibi baska proseslerden eklenen otomasyonlari cache stale olmadan goruyor.
- `update_last_run` ve `unregister` stale in-memory durumunda da lock altinda dogru sekilde calisacak hale getirildi.

Ek regresyon testleri:
- `tests/unit/test_automation_registry_modules.py`
  - `test_registry_get_active_refreshes_external_changes`
  - `test_registry_stale_instance_can_update_external_task`

Canli paralel kayit dogrulamasi (tekrar):
- Iki paralel `module-enable` kosusunda otomasyon sayisi `before=4` -> `after=6` olarak artip korunuyor.

Test kaniti (guncel):
- `python -m pytest -q tests/unit/test_automation_registry_modules.py tests/unit/test_agent_modules.py tests/unit/test_cli_command_wrappers.py tests/unit/test_cli_main.py` -> `33 passed`

### 14.10 Son Gelismeler (2026-03-10, gece update 5)

Scheduler hiz/dogruluk sertlestirmesi (module policy engine):
- `core/automation_registry.py` icinde module otomasyonlari icin policy alanlari eklendi:
  - `timeout_seconds`
  - `max_retries`
  - `retry_backoff_seconds`
  - `circuit_breaker_threshold`
  - `circuit_breaker_cooldown_seconds`
- Scheduler execution akisi `asyncio.wait_for` timeout + dahili retry/backoff + fail-streak/circuit-breaker modeline gecirildi.
- Runtime state persistence genisletildi:
  - `last_started_at`, `last_duration_ms`, `last_retry_count`, `last_timeout_seconds`
  - `fail_streak`, `next_retry_at`, `circuit_open_until`
- `get_module_health()` eklendi: module bazli saglik ozetini (healthy/failing/circuit_open/unknown) tek snapshotta uretiyor.

Gateway telemetry ve dashboard entegrasyonu:
- `core/gateway/server.py` icinde `/api/health/telemetry` ve WS telemetry payload'i module health detaylarini tasiyor.
- Dashboard'a yeni kart eklendi:
  - `ui/web/dashboard.html`: `Agent Modules Health`
  - `ui/web/dashboard.css`: `module-health` layout
  - `ui/web/dashboard.js`: telemetry'den module health render + canli WS update
- Boyla dashboard'da artik her module icin:
  - saglik durumu
  - fail streak
  - timeout
  - son kosu zamani
  - retry/circuit kalan sure
  gorulebiliyor.

Yeni regresyon guvencesi:
- `tests/unit/test_automation_registry_modules.py`
  - `test_execute_with_policy_retries_then_succeeds`
  - `test_execute_with_policy_opens_circuit_on_threshold`
  - `test_get_module_health_snapshot`

Test kaniti (guncel):
- `python -m pytest -q tests/unit/test_agent_modules.py tests/unit/test_automation_registry_modules.py tests/unit/test_cli_command_wrappers.py tests/unit/test_cli_main.py tests/unit/test_gateway_cli.py tests/unit/test_gateway_server_message.py tests/unit/test_main_gateway_entrypoint.py tests/unit/test_routine_engine.py` -> `77 passed`

Canli dogrulama:
- Gateway restart + health check basarili (`127.0.0.1:18789`).
- `/api/health/telemetry` icinde `automations.module_health.summary` ve `automations.module_health.modules` alanlari dolu donuyor.
- Mevcut run'da module health ozeti: `active_modules=6`, `healthy=6`, `failing=0`, `circuit_open=0`.

### 14.11 Son Gelismeler (2026-03-10, gece update 6)

CLI policy kontrolu (module-enable) genisletmesi:
- `elyan agents module-enable` komutuna scheduler policy flag'leri eklendi:
  - `--timeout`
  - `--retries`
  - `--backoff`
  - `--circuit-threshold`
  - `--circuit-cooldown`
- Bu alanlar `register_module(...)` uzerinden otomasyon kaydina persisted oluyor.

Automation Registry operasyonel kontrol eklentileri:
- Yeni API/metotlar:
  - `get_all()`
  - `set_status(task_id, status)`
  - `list_module_tasks(include_inactive=True)`
  - `run_task_now(task_id, agent)`
- Scheduler tarafinda outcome persistence tek noktaya alinip (`_persist_execution_outcome`) run-now ve scheduler path'leri hizalandi.

Gateway module automation API:
- Yeni endpoint'ler:
  - `GET /api/automations/modules`
  - `POST /api/automations/modules/action`
- Desteklenen aksiyonlar:
  - `run_now`
  - `pause`
  - `resume`
  - `remove`
- Endpoint'ler admin access ile korunuyor (loopback + admin token/cookie).

Dashboard module action kontrolu:
- `Agent Modules Health` kartinda her module task icin aksiyon butonlari eklendi:
  - `Run now`
  - `Pause/Resume`
  - `Remove`
- Dashboard yuklenirken `/api/automations/modules?include_inactive=1` ile tum module task listesi cekiliyor.
- WebSocket telemetry geldikce health satirlari canli guncelleniyor.

Canli dogrulama:
- Yeni endpoint smoke:
  - `GET /api/automations/modules` -> `ok=True`, task listesi donuyor.
  - `POST /api/automations/modules/action` -> `run_now`, `pause`, `resume` aksiyonlari basarili.
- CLI smoke:
  - `module-enable project_reality_check --timeout 45 --retries 2 --backoff 7 --circuit-threshold 2 --circuit-cooldown 300`
  - `automations.json` icinde policy alanlari dogru persisted.

Test kaniti (guncel):
- `python -m pytest -q tests/unit/test_automation_registry_modules.py tests/unit/test_cli_command_wrappers.py tests/unit/test_agent_modules.py tests/unit/test_cli_main.py tests/unit/test_gateway_cli.py tests/unit/test_gateway_server_message.py tests/unit/test_main_gateway_entrypoint.py tests/unit/test_routine_engine.py` -> `79 passed`

### 14.12 Son Gelismeler (2026-03-10, gece update 7)

Hata duzeltme ve mevcut akis iyilestirmeleri (yeni ozellik eklemeden):

1) Yanlis remove davranisi kapatildi:
- `POST /api/automations/modules/action` icinde `action=remove` ve bulunamayan `task_id` icin artik `404 task not found` donuyor.
- Daha once yanlis sekilde `200 ok` donuyordu.

2) Duplicate module-enable kaydi engellendi (upsert):
- `core/automation_registry.py::register_module(...)` artik ayni scope (`module_id + user_id + channel + params`) icin yeni satir acmak yerine mevcut kaydi guncelliyor.
- Boyla tekrar tekrar ayni module-enable cagrisinda otomasyon tablosu sismez; policy/interval alanlari mevcut kayitta update edilir.

3) Dashboard module health stabilizasyonu:
- `ui/web/dashboard.js::renderModuleHealth(...)` telemetry push'lari geldikce onceki task listesini koruyacak sekilde iyilestirildi.
- Bu sayede WS telemetry paketi task listesi tasimadiginda kart gecici bosalmiyor.
- Ozet satirina `Beklemede` (paused) sayisi eklendi.

4) Snapshot dogrulugu iyilestirmesi:
- `core/gateway/server.py::_module_automation_snapshot(...)` summary degerleri task listesinden turetiliyor.
- `paused` sayisi artik explicit olarak raporlaniyor.

Test kaniti (guncel):
- `python -m pytest -q tests/unit/test_automation_registry_modules.py tests/unit/test_gateway_server_message.py tests/unit/test_cli_command_wrappers.py tests/unit/test_agent_modules.py tests/unit/test_cli_main.py tests/unit/test_gateway_cli.py tests/unit/test_main_gateway_entrypoint.py tests/unit/test_routine_engine.py` -> `82 passed`

Canli dogrulama:
- duplicate enable smoke: otomasyon sayisi degismedi (`count_before=7`, `count_after=7`) -> upsert calisiyor.
- remove missing smoke: `404 {"ok": false, "error": "task not found"}`
- pause/resume smoke: summary `paused` degeri `1 -> 0` beklenen sekilde degisti.

### 14.13 Son Gelismeler (2026-03-10, gece update 8)

Operasyonel olgunluk artisi (tam yonetilebilir module automation):

1) CLI module operasyon paketi tamamlandi:
- Yeni komutlar:
  - `agents module-tasks`
  - `agents module-health`
  - `agents module-run-now <task_id>`
  - `agents module-pause <task_id>`
  - `agents module-resume <task_id>`
  - `agents module-remove <task_id>`
  - `agents module-update <task_id> [policy flags]`
  - `agents module-reconcile`
- Policy flag'leri (`--interval --timeout --retries --backoff --circuit-threshold --circuit-cooldown --status`) update path'inde de destekleniyor.

2) Registry katmaninda veri kalitesi + idempotency sertlestirmesi:
- `register_module(...)` upsert matching artik normalize edilmis params ile yapiliyor (workspace/path canonicalization).
- Yeni metotlar:
  - `update_module_task(...)`
  - `reconcile_module_tasks()`
- Duplicate module kayitlari tekilleştirme akisi eklendi (group fingerprint ile keep-latest policy).

3) Gateway module API genisletmesi:
- Yeni endpoint:
  - `POST /api/automations/modules/update`
- `POST /api/automations/modules/action` artik `task_ids` listesi ile bulk action destekliyor.
- Bulk action response'unda `requested/succeeded/failed/results` detaylari donuyor.
- `summary` artik snapshot task listesinden turetiliyor ve `paused` sayisi dahil.

4) Dashboard stabilizasyonu:
- Module health render'i telemetry-only update geldigi anda mevcut task listesini koruyacak sekilde hardened.
- Ozette `Beklemede` (`paused`) sayisi eklendi.

Test kaniti (guncel):
- `python -m pytest -q tests/unit/test_cli_command_wrappers.py tests/unit/test_automation_registry_modules.py tests/unit/test_gateway_server_message.py tests/unit/test_agent_modules.py tests/unit/test_cli_main.py tests/unit/test_gateway_cli.py tests/unit/test_main_gateway_entrypoint.py tests/unit/test_routine_engine.py` -> `90 passed`

Canli dogrulama:
- CLI smoke:
  - `module-health`, `module-tasks`, `module-update`, `module-resume` basarili.
- Gateway smoke:
  - `GET /api/automations/modules` -> `ok=True`
  - bulk `pause/resume` -> `succeeded=2, failed=0`
  - `POST /api/automations/modules/update` -> task policy update basarili.

### 14.14 NLU Iyilestirme Programi (2026-03-11)

Problem bildirimi:
- Kullanici geri bildirimi: "safariyi ac", "safari ac" gibi basit komutlar bazen beklenen sekilde algilanmiyor veya yanlis orkestrasyon yoluna gidiyor.
- Etki: basit komutlarda gereksiz planlama/ekran operatoru path'i, daha yavas ve daha az deterministik davranis.

Kok neden analizi:
1) Capability realignment kurali fazla agresifti.
- `core/pipeline.py::_should_realign_to_capability(...)` icinde `open_app/close_app` intentleri, parser confidence `0.9` altinda oldugunda kolayca `screen_operator` aksiyonlarina override olabiliyordu.
- Parser default confidence cogu path'te `0.85` oldugu icin "safari ac" gibi net komutlar gereksizce override riski tasiyordu.

2) Uygulama odaklama fiilleri eksikti.
- `core/intent_parser/_apps.py::_parse_open_app(...)` ac/kapat odakliydi; "safari'ye gec", "safari odaklan" gibi dogal varyasyonlar tam kapsanmiyordu.

3) Intent surecinde "basit komut" ve "UI operator gorevi" siniri yeterince net degildi.
- Ayni cagrida hem app acma hem UI eylemi oldugunda (or. "... ve continue butonuna tikla") screen operator'a yukselme gerekirken,
- yalniz app acma/kapama komutlari deterministic direct-intent olarak kalmali.

Uygulanan duzeltmeler (tamamlandi):
1) Simple app command override korumasi:
- `core/pipeline.py` icinde `screen_operator` realignment kurali guncellendi.
- `open_app/close_app` + operator step marker yoksa override artik her confidence seviyesinde engelleniyor.
- Boyla "safari ac" gibi net komutlar parser sonucunda kalir.

2) Dogal dil fiil kapsami genisletmesi:
- `core/intent_parser/_apps.py` icinde `open_app` parser'ina su fiiller eklendi:
  - `gec`, `don`, `odaklan`, `goster`, `switch`, `focus`
- Boyla su varyasyonlar da `open_app` olarak yakalaniyor:
  - `safariye gec`
  - `safari'ye gec`
  - `safari odaklan`

3) Regresyon testleri:
- `tests/test_intent_parser_regressions.py`
  - `test_open_app_focus_variants_route_to_open_app`
- `tests/unit/test_pipeline_team_mode.py`
  - `test_pipeline_capability_realign_skips_simple_open_app` (confidence `0.85` ile de guvence)
  - `test_pipeline_capability_realign_keeps_ui_control_phrase_for_screen_operator`

Test kaniti:
- `python -m pytest -q tests/test_intent_parser_regressions.py::test_open_app_focus_variants_route_to_open_app tests/unit/test_pipeline_team_mode.py::test_pipeline_capability_realign_skips_simple_open_app tests/unit/test_pipeline_team_mode.py::test_pipeline_capability_realign_keeps_ui_control_phrase_for_screen_operator` -> `3 passed`
- `python -m pytest -q tests/test_intent_parser_regressions.py tests/unit/test_pipeline_team_mode.py` -> `38 passed`

#### NLU Yol Haritasi (Roadmap)

R1 - Deterministik Dil Katmani (kisa vade):
1. Turkce morphology-lite normalize:
- apostrof/sonek ayrisma: `safari'ye`, `safariyi`, `safariden`
- ascii normalize + token boundary guvencesi
2. Verb intent class'lari:
- `open/focus`, `close`, `navigate`, `click`, `type`, `search`, `research`
3. Alias dictionary governance:
- app/site/eylem alias'lari tek kaynaktan version'li yonetim

R2 - Confidence Kalibrasyonu (kisa-orta vade):
1. Parser confidence'i statik `0.85` yerine signal-weighted skor ile uret.
2. Realignment guard:
- "deterministic command lock" (net tek adim komutta capability override kapali)
3. Intent conflict resolver:
- parser intent + capability intent + quick intent icin ortak tie-break kurali

R3 - Multi-step NLU (orta vade):
1. Komut parcacigi ayristirma:
- `ve sonra`, `ardindan`, numarali adimlar, implicit step baglantilari
2. UI eylem extraction:
- "X butonuna tikla", "Y alanina yaz", "enter bas" gibi operator-friendly slotlar
3. Direct-intent -> screen/operator escalation only-if-needed kurali

R4 - Ogrenme ve Izlenebilirlik (orta-uzun vade):
1. Intent telemetry:
- false-positive/false-negative etiketleri
- hangi kuralin override yaptigi (explainability)
2. Golden utterance set:
- Turkce agirlikli regression dataset
- her release'de otomatik NLU benchmark
3. Kullanici geri bildirim loop:
- "yanlis anladin" sinyallerinden alias/intent kural iyilestirme

#### Uc Uca NLU Algoritmasi (Hedef Tasarim)

Adim 1 - Normalize:
- Lowercase
- Turkce karakter normalize (opsiyonel ascii ikizi)
- Apostrof/sonek ayrimi (`safari'ye` -> `safari ye`)

Adim 2 - Token + Morph-lite:
- tokenization
- Turkce yaygin eklerin soyulmasi (yi/ye/den/de vb) ama semantik koruma ile

Adim 3 - Intent adaylari:
- Deterministik parser adaylari
- Capability router adayi
- Quick intent adayi

Adim 4 - Slot extraction:
- app_name, url, query, ui_target, text_payload, step connectors

Adim 5 - Skorlama:
- lexical match score
- slot completeness score
- ambiguity penalty
- historical reliability prior

Adim 6 - Conflict resolution:
- Basit deterministic komut lock:
  - tek app komutu -> direct intent
- UI/multi-step sinyali varsa:
  - `screen_workflow` veya `computer_use` escalation
- Arastirma/document sinyali varsa:
  - research/document workflow onceligi

Adim 7 - Execution + verify:
- secilen intent task-spec'e donusur
- calistirma sonrasi verify + evidence kaydi

Adim 8 - Online learning:
- kullanici duzeltmeleri + hata telemetrisi ile rule weight update

Basari KPI hedefleri:
- Basit app komutlarinda first-pass success: `>= %98`
- Multi-step UI komutlarinda dogru workflow secimi: `>= %95`
- "Yanlis anlama" geri bildirimi oraninda 30 gun icinde en az `%40` azalis

### 14.15 TaskSpec + NLU Training Hatti (2026-03-11)

Bu turde "Elyan dogal dili daha iyi anlayip, LLM'leri dogru secsin ve karmasik gorevleri sirali yurutsun" hedefi icin dogrudan kod degisiklikleri eklendi.

1) TaskSpec standardizasyonu (tek format):
- Yeni standartlayici eklendi:
  - `core/spec/task_spec_standard.py`
- Bu katman her TaskSpec'te su alanlari normalize ediyor:
  - `intent`
  - `slots`
  - `steps`
  - `depends_on`
  - `success_criteria`
- Step seviyesinde `depends_on` ve `success_criteria` yoksa otomatik uretiliyor.
- Root seviyede `success_criteria` yoksa adim/check/artifact verisinden turetiliyor.

2) Agent/Pipeline entegrasyonu:
- `core/agent.py`:
  - `_build_filesystem_task_spec`
  - `_build_api_task_spec`
  - `_build_task_spec_from_intent`
  - `_run_direct_intent`
  path'lerinde TaskSpec runtime oncesi standardize ediliyor.
- `core/pipeline.py`:
  - TaskSpec-first normalization asamasinda `coerce_task_spec_standard(...)` zorunlu cagriliyor.

3) TaskSpec validator sertlestirmesi:
- `core/spec/task_spec.py`:
  - `slots` ve `success_criteria` icin tip kontrolu eklendi.
  - DAG cycle detection eklendi (`invalid:steps.depends_on.cycle`).
- `core/spec/task_spec.schema.json`:
  - root: `slots`, `success_criteria`
  - step: `success_criteria`
  alanlari schema'ya eklendi.

4) Confidence + fallback netlestirme kapisi:
- `core/pipeline.py`:
  - yeni helper: `_build_low_confidence_actionable_clarification(...)`
  - Actionable ama non-actionable intent + dusuk guven durumunda sistem riskli isleme gitmeden netlestirme sorusu doner.
  - Bu gate delivery'yi bloke edip deterministic netlestirme ister.

5) NLU egitim veri hatti:
- Yeni moduller:
  - `core/nlu/__init__.py`
  - `core/nlu/dataset_builder.py`
- Yeni scriptler:
  - `scripts/build_nlu_dataset.py`
  - `scripts/nlu_benchmark.py`
- Dataset builder:
  - kaynak: `~/.elyan/runs/*/task.json`
  - etiketler: `intent`, `slots`, `steps`, `depends_on`, `success_criteria`, `confidence`
  - hard-negative: `feedback.json` duzeltmelerinden otomatik isaretleme
  - sentetik paraphrase uretimi (opsiyonel)
- smoke:
  - `python scripts/build_nlu_dataset.py --limit 200 --paraphrases-per-row 1 --output artifacts/nlu/nlu_dataset.jsonl` -> `rows=42`
  - `python scripts/nlu_benchmark.py --dataset artifacts/nlu/nlu_dataset.jsonl` -> `action_accuracy=0.5714`
  - `python scripts/train_nlu_baseline.py --dataset artifacts/nlu/nlu_dataset.jsonl --label-field action_label --model-out artifacts/nlu/baseline_intent_model.json` -> `eval_accuracy=0.7778`

6) Test guvencesi:
- Yeni testler:
  - `tests/unit/test_task_spec_standard.py`
  - `tests/unit/test_nlu_dataset_builder.py`
- Guncellenen testler:
  - `tests/unit/test_task_spec_validation.py` (cycle kontrol testi)
  - `tests/unit/test_pipeline_team_mode.py` (dusuk guven netlestirme testi)

Beklenen etki:
- Her actionable komut runtime'da tek bir normalize TaskSpec kontratina oturur.
- Karmasik adimli gorevlerde DAG bagimliliklari ve basari kriterleri daha net olur.
- Dusuk guvenli durumlarda yanlis aksiyon yerine kontrollu netlestirme akisi calisir.
- NLU egitimi icin dogrudan kullanilabilir Turkce agirlikli etiketli dataset uretilir.

### 14.16 Runtime Model-A Rescue + Simple Command Lock (2026-03-11)

Bu adimda "safari ac" gibi net komutlarin yanlis workflow'a kaymasini azaltmak ve LLM'e dusmeden once hizli NLU rescue katmani eklemek icin runtime guclendirildi.

1) Route asamasina Model-A rescue eklendi:
- `core/pipeline.py`
  - yeni policy helper: `_resolve_model_a_policy(ctx)`
  - yeni rescue helper: `_try_model_a_intent_rescue(...)`
  - akisa eklendi: deterministic fallback'lerden sonra, LLM rescue'dan once Model-A intent denemesi.
- Varsayilan politika:
  - `enabled=True`
  - `model_path=~/.elyan/models/nlu/baseline_intent_model.json`
  - `min_confidence=0.78`
  - `allowed_actions` default safe-list (open_app, web_search, file ops, http_request vb.)
- Runtime override kaynaklari:
  - config: `agent.nlu.model_a.*`
  - runtime policy: `runtime_policy.nlu.model_a.*`
  - metadata override: `model_a_enabled`, `model_a_path`, `model_a_min_confidence`

2) Capability fallback icin "simple app command lock":
- `core/pipeline.py`
  - yeni heuristic: `_looks_simple_app_control_command(text)`
  - `screen_workflow/vision_operator_loop/operator_mission_control` fallback'inde
    basit app ac/kapat komutlari (UI step marker yoksa) artik screen fallback'e yukselmiyor.
- Etki:
  - "safari ac" gibi komutlar gereksiz operator moduna kaymadan dogrudan app intent olarak kalir.

3) Agent tarafinda Model-A inference motoru:
- `core/agent.py`
  - model cache/state alanlari:
    - `_nlu_model_a`, `_nlu_model_a_path`, `_nlu_model_a_mtime`, `_nlu_model_a_load_error`
  - yeni methodlar:
    - `_model_a_default_path()`
    - `_load_model_a(model_path="")`
    - `_normalize_model_a_action(label)`
    - `_build_model_a_intent(action_label, user_input, confidence)`
    - `_infer_model_a_intent(user_input, min_confidence, model_path, allowed_actions)`
- Guvenlik:
  - dusuk confidence intent drop
  - non-actionable action drop
  - allowed-actions disi prediction drop
  - kritik aksiyonlarda parametre zorunlulugu (or. `open_app.app_name`, `http_request.url`, `run_safe_command.command`)

4) Test kapsami:
- `tests/unit/test_pipeline_team_mode.py`
  - `test_simple_app_control_command_guard`
  - `test_model_a_policy_defaults_without_runtime_overrides`
  - `test_model_a_intent_rescue_promotes_non_actionable_route`
- `tests/unit/test_agent_routing.py`
  - `test_agent_infer_model_a_intent_open_app`
  - `test_agent_infer_model_a_intent_run_safe_command`
  - `test_agent_infer_model_a_intent_rejects_not_allowed_action`

5) Calistirilan testler (kanit):
- `python -m pytest -q tests/unit/test_pipeline_team_mode.py -k "model_a or simple_app_control or low_confidence or capability_realign"` -> `8 passed`
- `python -m pytest -q tests/unit/test_agent_routing.py -k "infer_model_a_intent"` -> `3 passed`
- `python -m pytest -q tests/unit/test_pipeline_team_mode.py tests/test_intent_parser_regressions.py tests/unit/test_task_spec_validation.py tests/unit/test_task_spec_standard.py tests/unit/test_nlu_dataset_builder.py tests/unit/test_nlu_baseline_model.py` -> `58 passed`
- `python -m pytest -q tests/unit/test_agent_routing.py -k "task_spec or infer_model_a_intent"` -> `16 passed`

### 14.17 NLU Policy Hardening (Runtime + Gateway) (2026-03-11)

Model-A rescue'nin "opsiyonel kod" olarak kalmamasi icin NLU ayarlari runtime policy, config ve dashboard profile API'sine resmi olarak baglandi.

1) Runtime policy'ye NLU alani eklendi:
- `core/runtime_policy.py`
  - `RuntimePolicy` icine `nlu` field eklendi.
  - `resolve()` artik `agent.nlu.model_a.*` ayarlarini policy payload'ina koyuyor:
    - `enabled`
    - `model_path`
    - `min_confidence`
    - `allowed_actions`

2) Default config'e NLU baseline eklendi:
- `config/elyan_config.py`
  - `_default_config()` altina `agent.nlu.model_a` varsayilanlari eklendi.
  - Boylece yeni kurulumda Model-A policy deterministic sekilde mevcut.

3) Agent runtime context policy genisletildi:
- `core/agent.py`
  - pipeline context'e gecilen `ctx.runtime_policy` icine `nlu` blogu eklendi.
  - Route katmani artik policy'den NLU ayarlarini dogrudan okuyabiliyor.

4) Gateway profile API NLU support:
- `core/gateway/server.py`
  - `handle_agent_profile_get` cevabina `profile.nlu.model_a` eklendi.
  - `handle_agent_profile_update` tarafi `nlu.model_a` payload'ini kabul edip config'e kaydediyor:
    - `agent.nlu.model_a.enabled`
    - `agent.nlu.model_a.model_path`
    - `agent.nlu.model_a.min_confidence`
    - `agent.nlu.model_a.allowed_actions`
  - Validation:
    - `min_confidence` clamp: `[0.4, 0.99]`
    - `allowed_actions` normalize + bos ise safe default fallback

5) Test guvencesi:
- `tests/unit/test_runtime_policy.py`
  - `test_runtime_policy_resolve_includes_nlu_model_a_config`
- `tests/unit/test_gateway_server_message.py`
  - `test_handle_agent_profile_get_includes_nlu_model_a`
  - `test_handle_agent_profile_update_persists_nlu_model_a`

Calistirilan testler:
- `python -m pytest -q tests/unit/test_runtime_policy.py` -> `3 passed`
- `python -m pytest -q tests/unit/test_gateway_server_message.py -k "agent_profile"` -> `2 passed`
- `python -m pytest -q tests/unit/test_pipeline_team_mode.py tests/unit/test_agent_routing.py -k "model_a or simple_app_control or capability_realign"` -> `9 passed`
- `python -m pytest -q tests/unit/test_gateway_server_message.py tests/unit/test_runtime_policy.py` -> `23 passed`

### 14.18 App Control Reliability Fix (2026-03-11)

Kullanici geri bildirimi ("Safari ac / Chrome sekme ac islerini dogru yapmiyor") uzerine, sorun "intent"ten cok "aksiyon dogrulama ve odak yarisi (focus race)" olarak kapatildi.

1) `open_app` gercek odak dogrulamasi:
- `tools/system_tools.py`
  - `open_app(app_name, settle_timeout_s=1.2)`:
    - `open -a` sonrasi explicit `activate` calisir.
    - `System Events` ile frontmost app kisa sure poll edilir.
    - sonuca su alanlar eklenir:
      - `frontmost_app`
      - `verified`
      - `activated`
      - gerekirse `verification_warning`
- Boylece "opened" mesaji var ama odak baska app'teyse bu artik sonucta gorunur; sessiz yalanci basari azalir.

2) `key_combo` hedef uygulama kilidi:
- `tools/system_tools.py`
  - `key_combo(combo, target_app=None, settle_ms=120)`:
    - `target_app` verilirse once app activate edilir.
    - kisa bekleme sonra combo basilir.
    - frontmost hedefle uyusmuyorsa `success=False` + acik hata doner.
- Sonuc: "yeni sekme ac" kisayolu yanlis pencereye gitmez; giderse fail-fast olur.

3) Browser new-tab parser guclendirmesi:
- `core/intent_parser/_apps.py`
  - `chrome dan yeni sekme ac` benzeri komutlarda ikinci adim:
    - once: `{"combo":"cmd+t"}`
    - sonra: `{"combo":"cmd+t","target_app":"Google Chrome"}`

4) Kanit dosya adi tekillestirme:
- `core/agent.py`
  - riskli islem screenshot kanitlari artik timestamp'li:
    - `proof_<tool>_<ts>.png`
    - `wallpaper_proof_<ts>.png`
- Boyla eski kanit dosyasinin tekrar gosterilmesi riski azaltildi.

5) Test guvencesi:
- `tests/unit/test_system_tools.py`
  - `test_open_app_reports_frontmost_verification`
  - `test_key_combo_target_app_mismatch_returns_failure`
- `tests/test_intent_parser_regressions.py`
  - `test_browser_new_tab_command_routes_to_multi_task` icine `target_app` assertion eklendi.

Calistirilan testler:
- `python -m pytest -q tests/unit/test_system_tools.py -k "open_app_reports_frontmost_verification or key_combo_target_app_mismatch_returns_failure"` -> `2 passed`
- `python -m pytest -q tests/test_intent_parser_regressions.py -k "browser_new_tab_command_routes_to_multi_task"` -> `1 passed`
- `python -m pytest -q tests/unit/test_pipeline_team_mode.py tests/unit/test_agent_routing.py -k "model_a or capability_realign or simple_app_control"` -> `9 passed`
- `python -m pytest -q tests/unit/test_gateway_server_message.py tests/unit/test_runtime_policy.py tests/test_intent_parser_regressions.py` -> `46 passed`

### 14.19 Execution Truthfulness Hardening (2026-03-11)

Kullanici geri bildirimindeki ana problem ("islem oldu deniyor ama gercekte dogrulanmiyor") icin, app-control hattina truthfulness gate eklendi.

1) Direct intent execute'da app-control verification gate:
- `core/pipeline.py` / `StageExecute`
  - `open_app/close_app/key_combo/open_url` icin direct payload'da:
    - `verified=False` veya
    - `verification_warning` icinde uyumsuz/hedef disi sinyali
  gorulurse artik success kabul edilmiyor.
  - Bu durumda:
    - `ctx.errors += direct_intent_unverified:<action>`
    - kullaniciya "basarili" yerine dogrulama notu ile kontrollu fail donuyor.
- Ek: `set_wallpaper` direct proof dosya adi timestamp'li yapildi.

2) Result render truthfulness iyilestirmesi:
- `core/agent.py` / `_format_result_text`
  - app-control basarisizliklarinda generic "Hata" yerine hedef/odak/dogrulama detaylari gosteriliyor.
  - boylece operasyonda neyin yanlis gittigi acik sekilde iletiliyor.

3) Parser side target lock korundu:
- `core/intent_parser/_apps.py`
  - browser new-tab komutunda `key_combo` adimina `target_app` tasinmaya devam ediyor.

4) Ek testler:
- `tests/unit/test_pipeline_team_mode.py`
  - `test_stage_execute_marks_app_control_unverified_as_failure`
- `tests/unit/test_agent_routing.py`
  - `test_agent_format_result_text_renders_open_app_verification`
  - `test_agent_format_result_text_renders_key_combo_target_warning`

Calistirilan testler:
- `python -m pytest -q tests/unit/test_pipeline_team_mode.py -k "app_control_unverified"` -> `1 passed`
- `python -m pytest -q tests/unit/test_agent_routing.py -k "format_result_text_renders_open_app_verification or format_result_text_renders_key_combo_target_warning"` -> `2 passed`
- `python -m pytest -q tests/unit/test_system_tools.py -k "open_app_reports_frontmost_verification or key_combo_target_app_mismatch_returns_failure"` -> `2 passed`
- `python -m pytest -q tests/unit/test_pipeline_team_mode.py tests/test_intent_parser_regressions.py tests/unit/test_runtime_policy.py tests/unit/test_gateway_server_message.py tests/unit/test_agent_routing.py -k "model_a or app_control_unverified or browser_new_tab_command_routes_to_multi_task or format_result_text_renders or runtime_policy_resolve_includes_nlu_model_a_config or agent_profile"` -> `12 passed`

### 14.20 Multi-Task Scheduler + Short Response Stabilization (2026-03-11)

Kullanici geri bildirimi: "sirali gorevleri kaciriyor / uzun ve gereksiz cevap veriyor". Bu sprintte multi-task execution ve response policy birlikte sertlestirildi.

1) Multi-task runtime algoritmasi yenilendi (`core/agent.py`, `_run_direct_intent`):
- Eski davranis: listeyi sadece sira ile geziyordu, dependency/fail-fast/retry kontrolu zayifti.
- Yeni davranis (deterministic DAG-lite):
  - Her adim icin normalize: `id`, `action`, `params`, `depends_on`, `description`.
  - `depends_on` bos ise deterministic linear fallback (`prev_step`) atanir.
  - Bilinmeyen dependency aninda PLAN seviyesinde fail edilir.
  - Ready-set mantigi ile adimlar dependency tamamlandiginda kosulur.
  - UI yan-etkili aksiyonlar (`open_app`, `open_url`, `key_combo`, `type_text`, `mouse_*`, `computer_use`, `screen_*`) zorunlu serial kosulur.
  - UI-disi bagimsiz adimlar policy-limit dahilinde kismen parallel kosabilir.
  - Adim bazinda retry budget (default 2, max 4) uygulanir.
  - Fail-fast: bir adim kalici fail olursa sonraki bagimli adimlar kosulmaz.

2) Step success/failure kriterleri sertlestirildi:
- Tool `success=False` => fail.
- App-control adimlarinda `verified=False` => fail.
- Render edilen metinde `Hata:` / `Hata kodu:` / `basarisiz` sinyali => fail.
- Bu sayede "islem basarili gorundu ama gercekte degildi" vakalari azaltildi.

3) Multi-task output kontrati:
- `_last_direct_intent_payload` artik structured ozet tutar:
  - `success`, `total_steps`, `completed_steps`, `failed_step`, `steps[]`
- Pipeline bu payload'i kullanarak execution truthfulness'i daha dogru yorumlar.

4) Kisa cevap politikasi (gercekten kisa):
- `core/agent.py` runtime policy merge:
  - `response_length_bias=short` ise:
    - `response.mode=concise`
    - `response.friendly=False`
    - `response.compact_actions=True`
- `response.compact_actions=True` ise:
  - simple app-control cevaplari tek satira indirgenir (`Safari acildi.`, `Sayfa acildi.`, vb.)
  - multi-task sonucunda uzun step-dump yerine kisa ozet donulur:
    - `✅ N adim tamamlandi: ...`
    - veya `❌ k. adim basarisiz: ...`
- Bias yoksa compact mode zorlanmaz; test/regresyon stabil kalir.

4.1) Capability realignment guard (sub-agent/multi-agent over-trigger fix):
- `core/pipeline.py` / `_should_realign_to_capability(...)`:
  - `screen_operator` domain'inde `action=multi_task` ve komut basit app-control ise realignment iptal edilir.
  - Boylece "safari ac -> screen_workflow/team-mode" gibi gereksiz escalation azaltilir; deterministic multi-task path korunur.
- Ek test:
  - `tests/unit/test_pipeline_team_mode.py::test_pipeline_capability_realign_skips_simple_multi_task_app_flow`

5) Roadmap (siradaki zorunlu adimlar):
- P1: Multi-task DAG runner'i `TaskSpec` native executor ile birlestir (tek runtime).
- P2: Critic/verifier gate'i step-level zorunlu hale getir (her adim verify + retry policy).
- P3: Sub-agent scheduler ile direct multi-task arasina unified scheduling contract koy:
  - `intent + slots + steps + depends_on + success_criteria`
- P4: Compact response icin kanal/profil bazli policy matrix:
  - CLI: ultra short
  - docs/report: structured detailed
  - operator actions: short + truthfulness warning

6) Test guvencesi:
- `tests/unit/test_agent_routing.py`
  - `test_agent_run_direct_intent_multi_task_fail_fast_on_dependency`
  - `test_agent_run_direct_intent_compacts_multi_task_output_when_policy_enabled`
  - mevcut multi_task regressionlari yeni scheduler ile gecerli tutuldu.
- Calistirilan testler:
  - `python -m pytest -q tests/unit/test_agent_routing.py -k "multi_task or direct_intent or runtime_task_spec"` -> `21 passed`
  - `python -m pytest -q tests/unit/test_agent_routing.py` -> `138 passed`
  - `python -m pytest -q tests/unit/test_runtime_policy.py tests/test_intent_parser_regressions.py -k "model_a or browser_new_tab_command_routes_to_multi_task"` -> `2 passed`
  - `python -m pytest -q tests/unit/test_pipeline_team_mode.py tests/unit/test_runtime_policy.py tests/test_intent_parser_regressions.py tests/unit/test_system_tools.py -k "app_control_unverified or model_a or browser_new_tab_command_routes_to_multi_task or capability_realign or key_combo_target_app_mismatch_returns_failure or open_app_reports_frontmost_verification"` -> `11 passed`

### 14.21 TR NLU Komut Anlama Duzeltmeleri (2026-03-11)

Kullanici geri bildirimi:
- "Masaustundeki ekran resimlerini sil" komutu gereksiz netlestirme sorusuna dusuyordu.
- "Terminal ac ve elyan restart komutunu calistir" komutu yanlislikla `restart_system`e gidiyordu.

Uygulanan duzeltmeler:
1) Ekran goruntuleri icin dogal dil toplu silme:
- `core/intent_parser/_files.py::_parse_delete_file(...)`
  - "ekran resmi / screenshot" + "sil" + "resim/gorsel/foto" sinyali iceren cümleler artik
    `delete_file` aksiyonuna pattern-based params ile normalize ediliyor.
  - Ornek:
    - `directory=~/Desktop`
    - `patterns=[Ekran Resmi*, Ekran Goruntusu*, Screenshot*, Screen Shot *]`

2) `delete_file` araci pattern-batch modu kazandi:
- `tools/file_tools.py::delete_file(...)`
  - Eski tekil path silme davranisi korunarak,
  - yeni mode: `path="" + patterns + directory` ile eslesen dosyalari toplu silme.
  - Guvenlik:
    - path validation ayni guard uzerinden calisir.
    - `max_files` upper bound var.
    - dry-run desteklenir.

3) Agent param hazirlama uyumu:
- `core/agent.py::_prepare_tool_params(...)` / `delete_file` blogu
  - pattern-based batch delete payload'i varsa tekil path inference zorlanmaz.
  - directory normalize edilerek deterministic calisir.

4) Terminal komutu vs sistem restart ayrimi:
- `core/intent_parser/_system.py::_parse_power_control(...)`
  - "komutunu calistir / terminal / bash / shell / run / execute" baglami varsa
    power parser restart intentini tetiklemez.
  - Boyla "elyan restart komutunu calistir" -> `run_safe_command`,
    "bilgisayari yeniden baslat" -> `restart_system` olarak kalir.

Test guvencesi:
- `tests/unit/test_intent_parser_and_dashboard.py`
  - `test_delete_desktop_screenshot_images_routes_to_batch_delete_pattern`
- `tests/test_intent_parser_regressions.py`
  - `test_terminal_restart_command_phrase_routes_to_run_safe_command_not_restart_system`
  - `test_terminal_open_and_restart_command_routes_to_multi_task_without_restart_system`
- `tests/unit/test_file_tools_batch_delete.py`
  - batch delete success/no-match senaryolari

Calistirilan testler:
- `python -m pytest -q tests/unit/test_intent_parser_and_dashboard.py tests/test_intent_parser_regressions.py tests/unit/test_file_tools_batch_delete.py` -> `58 passed`
- `python -m pytest -q tests/unit/test_agent_routing.py -k "delete_file or prepare_delete or infer_general_tool_intent_delete_file_without_extension or multi_task"` -> `9 passed`

### 14.22 Terminal Komut Niyeti Sinif Duzeltmesi (2026-03-11)

Kullanici geri bildirimi:
- "terminalden ssh root komutunu çalıştır" ifadesi yalniz `open_app(Terminal)` calistirip komutu atliyordu.

Kok neden:
- `open_app` parser'i `terminal + calistir` kalibini erken yakaliyordu.
- `terminal command` parser'i pipeline'da daha sonra oldugu icin devreye giremiyordu.

Duzeltmeler:
1) `open_app` disambiguation guard (`core/intent_parser/_apps.py`):
- `terminal + komut + calistir` baglami varsa `open_app` erken cikis yapar.
- Bu sinif cümleler terminal command parser'ina birakilir.

2) `terminal command` parser sertlestirmesi:
- Daha dogru extraction patternleri:
  - `terminalden/de ... komutunu calistir`
  - `... komutunu calistir`
  - `run/execute ...`
- Terminal baglami varsa artik deterministic `multi_task` uretilir:
  - `open_app(Terminal)` -> `run_safe_command(command)`
- Tek kelime fiiller (`ac`, `calistir`, `run`) komut olarak kabul edilmez.

3) Test guvencesi:
- `tests/test_intent_parser_regressions.py`
  - `test_terminalden_ssh_root_command_routes_to_terminal_multi_task`
  - `test_terminal_open_phrase_routes_to_open_app_not_command_execution`
  - ilgili terminal restart/regression testleri

Calistirilan testler:
- `python -m pytest -q tests/test_intent_parser_regressions.py -k "terminalden_ssh_root_command_routes_to_terminal_multi_task or terminal_open_phrase_routes_to_open_app_not_command_execution or terminal_restart_command_phrase_routes_to_run_safe_command_not_restart_system or terminal_open_and_restart_command_routes_to_multi_task_without_restart_system or open_app_focus_variants_route_to_open_app"` -> `5 passed`
- `python -m pytest -q tests/unit/test_intent_parser_and_dashboard.py tests/test_intent_parser_regressions.py` -> `58 passed`

### 14.23 Terminal Komut Gercek Calistirma Duzeltmesi (2026-03-11)

Kullanici geri bildirimi:
- `terminalden cd desktop komutu calistir` cevabi basarili gorunse de pratikte sadece Terminal aciliyor, komut beklenen sekilde calismiyordu.

Kok neden:
1) Komut extraction `komutu` son ekini birakabiliyordu (`cd desktop komutu`).
2) `terminalden ...` sinifi `run_safe_command` ile arka planda kosuyordu; `cd` gibi stateful komutlar Terminal UI tarafinda gorunur etki vermiyordu.

Uygulanan duzeltmeler:
1) Terminal komut normalize katmani:
- `core/intent_parser/_apps.py`
  - `_normalize_terminal_command(...)` eklendi.
  - `komutu/command` ve `calistir/run` son ek temizligi iyilestirildi.
  - `cd desktop` / `cd masaustu` => `cd ~/Desktop` normalize edildi.
2) `terminalden ... komutu calistir` execution mode degisimi:
- `core/intent_parser/_apps.py::_parse_terminal_command(...)`
  - `open_app(Terminal)` + `type_text(text=<command>, press_enter=True)` olarak deterministic multi_task uretiyor.
  - Boylece komut Terminal penceresine gercekten yazilip Enter ile calistiriliyor.
3) Sirali komutlarda terminal baglami koruma:
- `core/intent_parser/__init__.py::_parse_multi_task(...)`
  - `open_app(Terminal)` sonrasindaki `run_safe_command` adimi otomatik `type_text+enter` adimina donusturuluyor.
  - Ornek: `Terminal ac ve elyan restart komutunu calistir`.
4) Agent-level extraction hardening:
- `core/agent.py::_extract_terminal_command_from_text(...)`
  - `terminalden/terminalde` regex boundary ve suffix temizligi iyilestirildi.
  - Ayni `cd ~/Desktop` normalize mantigi eklendi.

Ek kalite iyilestirmesi:
- `core/response_tone.py`
  - `run_safe_command` sonucunda `stdout/stderr/returncode` anahtarlariyla uyumlu render eklendi.
- `core/agent.py::_format_result_text(...)`
  - `run_safe_command` tarzı `stdout/stderr/returncode` payloadlari daha dogru metinlestiriliyor.

Test guvencesi:
- `tests/test_intent_parser_regressions.py`
  - `test_terminalden_cd_desktop_command_normalizes_and_routes_to_terminal_ui`
  - terminal regression testleri `type_text` akisina guncellendi.
- `tests/unit/test_agent_routing.py`
  - `test_agent_extract_terminal_command_cleans_komutu_suffix`

Calistirilan testler:
- `python -m pytest -q tests/test_intent_parser_regressions.py tests/unit/test_agent_routing.py -k "terminal or extract_terminal_command or run_safe_command"` -> `10 passed`
- `python -m pytest -q tests/unit/test_intent_parser_and_dashboard.py tests/test_intent_parser_regressions.py tests/unit/test_file_tools_batch_delete.py` -> `61 passed`

### 14.24 Deterministic Operasyon Mimarisi - Failure Class Kernel (2026-03-11)

Stratejik hedef:
- Elyan'i "tool success" yerine "task success" odakli deterministik operasyon sistemine yaklastirmak.
- Kör retry yerine teshis tabanli recovery altyapisi kurmak.

Bu adimda uygulanan cekirdek degisiklik:
1) 5-sinif failure taxonomy (teshis katmani) eklendi:
- Yeni dosya: `core/failure_classification.py`
- Siniflar:
  - `perception_failure`
  - `planning_failure`
  - `tool_failure`
  - `state_mismatch`
  - `policy_block`
  - (`unknown_failure` fallback)
- Girisler:
  - `reason` metni
  - `error_code`
  - `failed_codes` (contract/verifier code listesi)
  - opsiyonel payload/action

2) Multi-task execution telemetry zenginlestirildi:
- `core/agent.py`
  - `_run_direct_intent` adim sonucuna `failure_class` eklendi.
  - `_last_direct_intent_payload` artik `failure_class` alanini da tasiyor.
  - Runtime TaskSpec adimlarinda (`_run_runtime_task_spec`) adim bazinda `failure_class` üretiliyor.

3) Verify stage capability gate teshisi eklendi:
- `core/pipeline.py::StageVerify`
  - `capability_runtime` fail durumunda `capability_failure` objesi uretiliyor:
    - `class`
    - `failed`
    - `failed_codes`
  - Runtime trace `verifier_results` icine capability failure sinifi yaziliyor.

Etkisi:
- Retries ve recovery stratejileri artik "neden basarisiz oldu?" sorusuna sinif bazli cevap uretebilir.
- Perception/plan/tool/state/policy ayrimi sayesinde sonraki adimda class-aware recovery policy yazilabilir.

Test guvencesi:
1) Yeni unit testler:
- `tests/unit/test_failure_classification.py`
  - policy/perception/state/planning/tool siniflandirma senaryolari
2) Entegrasyon/regression testleri:
- `tests/unit/test_pipeline_refactor_upgrade.py`
  - capability runtime fail durumunda capability failure kaydi
- `tests/unit/test_agent_routing.py`
  - direct multi-task fail-fast payload'inda failure class

Calistirilan testler:
- `python -m pytest -q tests/unit/test_failure_classification.py tests/unit/test_pipeline_refactor_upgrade.py -k "failure_class or capability_runtime or file_ops_when_runtime_contract_fails"` -> `7 passed`
- `python -m pytest -q tests/unit/test_agent_routing.py -k "multi_task_fail_fast_on_dependency or extract_terminal_command_cleans_komutu_suffix"` -> `2 passed`
- `python -m pytest -q tests/unit/test_intent_parser_and_dashboard.py tests/test_intent_parser_regressions.py tests/unit/test_file_tools_batch_delete.py tests/unit/test_failure_classification.py` -> `66 passed`

### 14.25 Conversation/Assist/Operator Ayrimi + Class-Aware Retry Policy (2026-03-11)

Stratejik hedef:
- "Akilli chat araci" ile "is yapan operator" sinirini deterministik ayirmak.
- Kör retry yerine failure-class tabanli retry politikasi uygulamak.

Uygulanan degisiklikler:

1) Runtime Policy'ye resmi execution katmani eklendi
- `core/runtime_policy.py`
  - `RuntimePolicy.execution` alanı eklendi.
  - Yeni config anahtarlari:
    - `agent.execution.mode` (`chat|assist|operator`, varsayılan: `operator`)
    - `agent.execution.derive_from_operator_mode` (varsayılan: `false`)
    - `agent.execution.assist_preview_max_steps` (varsayılan: `6`)
  - Preset baglantisi:
    - `strict -> assist`
    - `balanced -> operator`
    - `full-autonomy -> operator`

2) Agent -> Pipeline policy aktarimi guncellendi
- `core/agent.py`
  - `ctx.runtime_policy` icine `execution` bolumu eklendi.
  - `metadata.execution_mode` / `metadata.agent_mode` override destegi eklendi.
  - `autonomy_mode=full` durumunda execution mode deterministic olarak `operator` setleniyor.

3) StageExecute'ta Conversation Brain boundary eklendi
- `core/pipeline.py`
  - Yeni helperlar:
    - `_normalize_execution_mode(...)`
    - `_resolve_execution_mode(...)`
    - `_build_assist_mode_preview(...)`
  - Mode davranisi:
    - `chat`: actionable komutlar execute edilmez, sadece plan/preview doner.
    - `assist`: execute yok, deterministic preview doner.
    - `operator`: mevcut tam icra akisi.
  - Bu ayrim StageExecute'da tool cagrilarindan once uygulanir.

4) Class-aware retry policy (policy_block fail-fast)
- `core/agent.py`
  - `_run_direct_intent` icindeki multi-step executor:
    - her fail'de `failure_class` hesaplanir
    - `policy_block` sinifinda retry aninda durdurulur (blind retry yok)
  - `_run_runtime_task_spec` icindeki step loop:
    - `failure_class` attempt bazli hesaplanir
    - `policy_block` sinifinda fail-fast uygulanir

Etkisi:
- Conversation/Assist/Operator ayrimi artik runtime policy ile net olarak denetlenebilir.
- Risk/policy kaynakli bloklarda gereksiz tekrar denemeleri kesilir.
- Deterministik operasyon modeli bir kademe daha kurumsal hale geldi.

Test guvencesi:

1) Yeni/guncel testler:
- `tests/unit/test_pipeline_team_mode.py`
  - execution mode çözümleme
  - assist mode preview-only execution guard
  - chat mode actionable-block guard
- `tests/unit/test_runtime_policy.py`
  - execution.mode çözümleme
  - strict preset -> assist mode
- `tests/unit/test_agent_routing.py`
  - `policy_block` için fail-fast (retry yok)

2) Calistirilan testler:
- `python -m pytest -q tests/unit/test_runtime_policy.py tests/unit/test_pipeline_team_mode.py -k "execution_mode or assist_mode or chat_mode or runtime_policy"` -> `9 passed`
- `python -m pytest -q tests/unit/test_agent_routing.py -k "policy_block_fail_fast_no_blind_retry or multi_task_fail_fast_on_dependency or extract_terminal_command_cleans_komutu_suffix"` -> `3 passed`
- `python -m pytest -q tests/unit/test_intent_parser_and_dashboard.py tests/test_intent_parser_regressions.py tests/unit/test_file_tools_batch_delete.py tests/unit/test_failure_classification.py tests/unit/test_pipeline_refactor_upgrade.py tests/unit/test_pipeline_team_mode.py tests/unit/test_runtime_policy.py` -> `119 passed`

### 14.26 Class-Aware Recovery Policy Table (2026-03-11)

Stratejik hedef:
- Failure class tespitini aktif recovery politikasina baglamak.
- Kör retry yerine deterministic class-aware recovery uygulamak.

Uygulanan degisiklikler:

1) Recovery policy katmani eklendi:
- Yeni dosya: `core/recovery_policy.py`
- `select_recovery_strategy(...)` kurallari:
  - `policy_block` -> `fail_fast` (retry yok)
  - `planning_failure` (hard plan hatalari) -> `fail_fast`
  - `state_mismatch` + UI action -> `refocus_app`
  - `tool_failure` + terminal command -> `patch_params` (komut normalize)

2) Agent step executor'lara class-aware recovery baglandi:
- `core/agent.py`
  - Yeni helper: `_apply_failure_recovery_strategy(...)`
  - `_run_direct_intent` adim loop:
    - failure class hesapla
    - strategy uygula (refocus/patch/fail-fast)
    - `recovery_notes` telemetriye yaz
  - `_run_runtime_task_spec` step loop:
    - ayni class-aware strategy uygulanir
    - `recovery_notes` ve `failure_class` adim sonucuna eklenir

3) Deterministic retry guard:
- Recovery, sadece `attempt < attempts` iken uygulanir.
- Son denemede gereksiz ek recovery aksiyonu tetiklenmez.

Etkisi:
- `policy_block` gibi durumlarda gereksiz tekrar denemeleri kesildi.
- `state_mismatch` hatalarinda app refocus ile bir sonraki deneme daha tutarli hale geldi.
- Runtime/Direct path telemetrisi recovery adimlarini da acikca tasiyor.

Test guvencesi:

1) Yeni testler:
- `tests/unit/test_recovery_policy.py`
  - policy fail-fast
  - state mismatch refocus
  - tool failure command normalize

2) Guncellenen testler:
- `tests/unit/test_agent_routing.py`
  - direct path state-mismatch refocus davranisi
  - runtime TaskSpec policy-block fail-fast (retry yok)
  - mevcut fail-fast testi recovery-aware olacak sekilde guncellendi

3) Calistirilan testler:
- `python -m pytest -q tests/unit/test_recovery_policy.py tests/unit/test_failure_classification.py` -> `8 passed`
- `python -m pytest -q tests/unit/test_agent_routing.py -k "multi_task_fail_fast_on_dependency or state_mismatch_refocuses_before_retry or policy_block_fail_fast_without_retry or policy_block_fail_fast_no_blind_retry"` -> `4 passed`
- `python -m pytest -q tests/unit/test_recovery_policy.py tests/unit/test_pipeline_team_mode.py tests/unit/test_runtime_policy.py -k "recovery_policy or execution_mode or assist_mode or chat_mode or runtime_policy"` -> `12 passed`
- `python -m pytest -q tests/unit/test_intent_parser_and_dashboard.py tests/test_intent_parser_regressions.py tests/unit/test_file_tools_batch_delete.py tests/unit/test_failure_classification.py tests/unit/test_recovery_policy.py tests/unit/test_pipeline_refactor_upgrade.py tests/unit/test_pipeline_team_mode.py tests/unit/test_runtime_policy.py tests/unit/test_agent_routing.py` -> `264 passed`

### 14.27 Direct Intent Fail-Fast Regression Fix (2026-03-11)

Sorun:
- `StageExecute` direct-intent path'inde `policy_block` sinifina ait failure class bazen payload'dan gelmiyordu.
- Bu durumda sistem yanlislikla fallback path'e gecip "islem tamamlandi" benzeri false-positive uretebiliyordu.

Kok neden:
- Bazi agent implementasyonlarinda `_last_direct_intent_payload` set edilmediginde `failure_class` bos kalabiliyordu.
- Fail-fast kontrolu sadece payload tabanli siniflandirmaya dayaniyordu.

Duzeltme:
- `core/pipeline.py`
  - Yeni helper: `_infer_failure_class_from_text(...)`
  - `direct_failure_class` artik:
    - once payload (`_extract_direct_failure_class`)
    - yoksa direct response text'ten infer edilir
  - `policy_block` / `planning_failure` siniflari text tabanli da yakalanip fallback deterministik olarak engellenir.

Etkisi:
- Security/policy kaynakli bloklarda fallback path kapanir.
- Sistem yanlis "basarili" akislara dusmeden dogrudan blok mesaji ile doner.
- Deterministik operation boundary daha tutarli hale geldi.

Test guvencesi:
- `python -m pytest -q tests/unit/test_pipeline_team_mode.py -k "direct_policy_block or assist_mode or chat_mode or execution_mode"` -> `5 passed`
- `python -m pytest -q tests/unit/test_recovery_policy.py tests/unit/test_failure_classification.py tests/unit/test_pipeline_team_mode.py tests/unit/test_runtime_policy.py tests/unit/test_agent_routing.py` -> `180 passed`
- `python -m pytest -q tests/unit/test_intent_parser_and_dashboard.py tests/test_intent_parser_regressions.py tests/unit/test_file_tools_batch_delete.py tests/unit/test_failure_classification.py tests/unit/test_recovery_policy.py tests/unit/test_pipeline_refactor_upgrade.py tests/unit/test_pipeline_team_mode.py tests/unit/test_runtime_policy.py tests/unit/test_agent_routing.py` -> `265 passed`

### 14.28 Evidence False-Positive + Compact Response Hardening (2026-03-11)

Sorun:
- `goal_graph` constraint parser'inda `"ss"` substring eslesmesi oldugu icin
  `ssh` gibi komutlar yanlislikla evidence/proof istegi olarak algilaniyordu.
- Bu da bazi basit komutlarda gereksiz screenshot/artifact davranisina ve uzun cevaplara yol aciyordu.
- Ayrica compact mode'da multi-step basari cevaplari gereksiz detayliydi.

Uygulanan degisiklikler:

1) Evidence marker tespiti regex-boundary ile guclendirildi
- `core/goal_graph.py`
  - `requires_evidence` artik regex pattern'lerle tespit ediliyor.
  - `"ss"` sadece standalone token (`\\bss\\b`) ise screenshot niyeti sayiliyor.
  - `ssh` benzeri kelimelerde false-positive engellendi.

2) Compact response varsayilani aktif edildi
- `core/runtime_policy.py`
  - Tum presetlerde: `agent.response_style.compact_actions = True`
  - Resolve edilen response policy'ye eklendi:
    - `response.compact_actions` (varsayilan `True`)

3) Multi-task compact yanit daha kisa hale getirildi
- `core/agent.py`
  - Basarili compact multi-task yaniti artik adim label'larini saymiyor:
    - yeni format: `✅ N adım tamamlandı.`

Test guvencesi:

1) Yeni test:
- `tests/unit/test_goal_graph.py`
  - `test_goal_graph_ssh_phrase_does_not_trigger_evidence_mode`

2) Yeni test:
- `tests/unit/test_runtime_policy.py`
  - `test_runtime_policy_defaults_to_compact_action_responses`

3) Calistirilan testler:
- `python -m pytest -q tests/unit/test_goal_graph.py tests/unit/test_runtime_policy.py tests/unit/test_agent_routing.py -k "goal_graph or runtime_policy or compacts_multi_task_output"` -> `10 passed`
- `python -m pytest -q tests/unit/test_intent_parser_and_dashboard.py tests/test_intent_parser_regressions.py tests/unit/test_file_tools_batch_delete.py tests/unit/test_goal_graph.py tests/unit/test_failure_classification.py tests/unit/test_recovery_policy.py tests/unit/test_pipeline_refactor_upgrade.py tests/unit/test_pipeline_team_mode.py tests/unit/test_runtime_policy.py tests/unit/test_agent_routing.py` -> `269 passed`

### 14.29 Product-Grade Operator Roadmap + World Model Bootstrap (2026-03-11)

Nihai urun tanimi netlestirildi:
- Elyan = komut alan chatbot degil
- Elyan = amac anlayan, gorevi normalize eden, planlayan, dogru tool/model/agent secen, isi tamamlayan, sonucu dogrulayan ve tecrubeden ogrenerek daha iyi hale gelen dijital operator

Stratejik yon:
- AGI once "guvenilir operator" olarak insa edilir.
- Otonomluk, stabil execution ve verify katmanindan sonra gelir.
- Prompt-first degil, schema-first ve policy-first mimari izlenir.

Resmi urun fazlari:

Faz 1 - Core standardization
- input gateway
- intent engine
- task normalizer
- planner
- agent orchestrator
- tool registry
- execution engine
- validator
- memory layer
- response composer
- telemetry/logs
- Tum gorevler ortak task schema ile normalize edilir:
  - `task_id`
  - `user_goal`
  - `intent`
  - `entities`
  - `constraints`
  - `deliverables`
  - `priority`
  - `risk_level`
  - `tool_candidates`
  - `success_criteria`

Faz 2 - LLM communication protocol
- Rol bazli model dagitimi:
  - planner
  - research
  - coder
  - critic
  - summarizer
- LLM'e serbest prompt degil, gorev semasi + aktif adim + tool schema + basari kriteri + sinirlar verilir.

Faz 3 - Planner + Orchestrator
- Goal -> DAG -> agent queue -> tool execution -> verification
- Dependency resolution zorunlu
- Retry/timeout/fallback deterministic policy ile calisir

Faz 4 - Tool discipline
- Her tool icin:
  - `name`
  - `description`
  - `category`
  - `input_schema`
  - `output_schema`
  - `side_effects`
  - `risk_level`
  - `requires_confirmation`
  - `validation_rules`
  - `rollback_strategy`
- LLM tool calistirmaz; yalnizca tool karari uretir.

Faz 5 - Validator + self-correction
- `done != verified`
- Akis:
  - plan -> execute -> validate -> critique -> revise -> re-validate

Faz 6 - Memory hierarchy
- short-term memory
- working memory
- episodic memory
- semantic memory
- user profile memory
- Memory retrieval yalnizca hatirlama icin degil, strateji secimi icin kullanilir.

Faz 7 - Experience learning + policy engine
- Her gorev sonrasi:
  - plan
  - models
  - tool zinciri
  - hatalar
  - basari puani
  - sure / maliyet
  persisted edilir.
- Policy kurallari prompt'ta degil core logic'te tutulur.

Faz 8 - Computer control hardening
- vision parser
- UI state interpreter
- action executor
- optimistic execution yasak
- her adim sonrasi state transition verify zorunlu

Faz 9 - Otonomluk
- once suggestion mode
- sonra guven skoru yuksek alanlarda kontrollu delegation

Faz 10 - Long-term AGI layers
- world model
- causal reasoning
- recursive self-improvement
- goal hierarchy
- multi-session intelligence

Bu iterasyonda kodlanan ilk AGI-yonelimli cekirdek:

1) World model modulu eklendi
- Yeni dosya: `core/world_model.py`
- Yetenekleri:
  - `facts` tablosu ile lightweight symbolic state
  - `experiences` tablosu ile experience memory
  - benzer gorev arama
  - domain/strategy hint cikarimi
  - planlama oncesi world snapshot uretimi

2) Pipeline route entegrasyonu
- `core/pipeline.py`
  - Intent parse sonrasinda `ctx.world_snapshot` dolduruluyor.
  - Telemetry'ye:
    - `domains`
    - `strategy_count`
    - `experience_hits`
    yaziliyor.

3) Working set guclendirmesi
- `core/pipeline_upgrade/router.py`
  - planner working set artik:
    - world snapshot summary
    - strategy hints
    tasiyor.
- Bu, planner/LLM tarafina sadece chat history degil, operasyonel baglam da veriyor.

4) Experience learning loop entegrasyonu
- `core/pipeline.py`
  - delivery sonunda non-chat gorevler `world_model.record_experience(...)` ile kaydediliyor.
  - Kaydedilen alanlar:
    - `goal`
    - `action`
    - `job_type`
    - `plan`
    - `tool_calls`
    - `errors`
    - `final_response`
    - `verified`
    - `success_score`
    - metadata

Urun KPI odak guncellemesi:
- Ana kalite metri gi: `verified_success_rate`
- Sifira inmesi gereken metrik: `empty_artifact_rate`
- Ayrica izlenecek:
  - `task_completion_rate`
  - `tool_call_accuracy`
  - `retry_rate`
  - `hallucinated_action_rate`
  - `user_correction_rate`
  - `cost_per_successful_task`
  - `avg_time_to_verified_completion`

Tasarim ilkeleri (degismez kurallar):
- LLM karar verir, sistem uygular.
- Gorev verified ise done sayilir.
- Tool schema ve tool output standard olmalidir.
- Memory strateji secimi icin kullanilmalidir.
- Otonomluk, guvenilirlikten sonra gelir.
- Prompt engineering tek basina urun mimarisi degildir.

Test guvencesi:
- Yeni testler:
  - `tests/unit/test_world_model.py`
  - `tests/unit/test_pipeline_team_mode.py::test_stage_route_populates_world_snapshot`
- Calistirilan testler:
  - `python -m pytest -q tests/unit/test_world_model.py tests/unit/test_pipeline_team_mode.py -k "world_snapshot or world_model or execution_mode or assist_mode or chat_mode"` -> `7 passed`
- `python -m pytest -q tests/unit/test_world_model.py tests/unit/test_goal_graph.py tests/unit/test_pipeline_team_mode.py tests/unit/test_runtime_policy.py tests/unit/test_agent_routing.py` -> `179 passed`
- `python -m compileall -q core/world_model.py core/pipeline.py core/pipeline_upgrade/router.py tests/unit/test_world_model.py tests/unit/test_pipeline_team_mode.py` -> `ok`

### 14.30 TaskSchema v2 Hardening (2026-03-11)

Roadmap uyumlu hedef:
- Faz 1 core standardization maddesindeki task schema'yi "gevsek metadata" olmaktan cikarip gercek operasyon kontrati haline getirmek.
- Planner / execution / validator arasindaki veri akisi daha az serbest, daha cok sema-destekli hale getirildi.

TaskSchema v2 degisikligi:
- `core/spec/task_spec.py`
  - schema version `1.2`
  - artik root seviyede su alanlar zorunlu:
    - `task_id`
    - `goal`
    - `user_goal`
    - `entities`
    - `deliverables`
    - `constraints`
    - `required_tools`
    - `tool_candidates`
    - `priority`
    - `risk_level`
    - `success_criteria`
    - mevcut timeout/retry/steps alanlari

- `core/spec/task_spec.schema.json`
  - JSON schema da ayni kontrati yansitacak sekilde guncellendi.
  - `deliverables` icin item contract:
    - `name`
    - `kind`
    - `required`
  - `priority` enum:
    - `low`
    - `normal`
    - `high`
    - `critical`

Standardization/coercion guclendirmesi:
- `core/spec/task_spec_standard.py`
  - yeni standard version: `1.2`
  - eksik alanlar otomatik turetiliyor:
    - `task_id`
    - `user_goal`
    - `entities`
    - `deliverables`
    - `tool_candidates`
    - `priority`
    - `risk_level`
    - `required_tools`
    - `timeouts`
    - `retries`
  - `deliverables` artifact/step/goal verisinden turetiliyor.
  - `tool_candidates` required tool veya step action'larindan turetiliyor.
  - `risk_level` step action tipine gore heuristic ile normalize ediliyor.

Neden kritik:
- Elyan ile LLM/Planner arasi kontrat artik sadece `goal + steps` degil.
- Sistem artik:
  - neyin teslim edilmesi gerektigini (`deliverables`)
  - hangi varliklari algiladigini (`entities`)
  - hangi araclara aday oldugunu (`tool_candidates`)
  - bu isin ne kadar acil/riskli oldugunu (`priority`, `risk_level`)
  deterministik olarak tasiyor.

Etkisi:
- Planner daha net baglam aliyor.
- Execution engine daha denetlenebilir task payload goruyor.
- Validator asamasi "neyi dogrulayacagini" daha acik biliyor.
- Memory/experience katmani artik daha zengin task kaydi tasiyabiliyor.

Test guvencesi:
- Guncellenen testler:
  - `tests/unit/test_task_spec_standard.py`
  - `tests/unit/test_task_spec_validation.py`
- Calistirilan testler:
- `python -m pytest -q tests/unit/test_task_spec_standard.py tests/unit/test_task_spec_validation.py` -> `15 passed`
- `python -m pytest -q tests/unit/test_task_spec_standard.py tests/unit/test_task_spec_validation.py tests/unit/test_pipeline_team_mode.py tests/unit/test_agent_routing.py tests/unit/test_world_model.py` -> `186 passed`

### 14.31 Validator Profiles + TaskSpec Verify Gate (2026-03-11)

Roadmap uyumlu hedef:
- Faz 5 validator/self-correction katmanini gercekten TaskSchema kontratina baglamak.
- `done != verified` ilkesini belge/kod/research gorevleri icin daha somut hale getirmek.

Uygulanan degisiklikler:

1) TaskSpec verify contract eklendi
- `core/pipeline_upgrade/verifier.py`
  - yeni fonksiyon: `verify_taskspec_contract(...)`
  - girdiler:
    - `task_spec`
    - `job_type`
    - `final_response`
    - `tool_results`
    - `produced_paths`
  - kontrol eder:
    - `deliverables`
    - `artifacts_expected`
    - root `success_criteria`
    - required artifact varligi
    - artifact non-empty durumu
    - response gerekliligi

2) Validator profile mantigi eklendi
- `verify_taskspec_contract(...)` icinde profile secimi:
  - `code`
  - `research`
  - `document`
  - `generic`
- Ornek:
  - document profile:
    - eksik artifact -> fail
    - bos dosya -> fail
  - code profile:
    - artifact yoksa fail
  - research profile:
    - response yoksa fail

3) Reflexion hint eklendi
- `core/pipeline_upgrade/verifier.py`
  - yeni fonksiyon: `build_reflexion_hint(...)`
- Verify fail durumunda kullaniciya/sonraki loop'a hedefli bir onarim yonu veriyor.
- Bu daha sonra tam revise/re-run loop'a baglanacak.

4) StageVerify entegrasyonu
- `core/pipeline.py`
  - strict verify gate acikken:
    - `ctx.intent["task_spec"]` okunur
    - `verify_taskspec_contract(...)` calistirilir
    - `ctx.qa_results["taskspec_contract"]` doldurulur
    - fail varsa:
      - `ctx.verified = False`
      - `ctx.delivery_blocked = True`
      - `taskspec:*` error kodlari eklenir
      - `Reflexion next: ...` satiri final response'a eklenir

5) pipeline_upgrade export guncellemesi
- `core/pipeline_upgrade/__init__.py`
  - yeni exportlar:
    - `verify_taskspec_contract`
    - `build_reflexion_hint`

Etkisi:
- Elyan artik sadece "tool success"e bakmiyor.
- TaskSpec'in vaat ettigi deliverable ve success criteria da verify asamasina giriyor.
- Ozellikle belge/dosya odakli gorevlerde bos artifact artik daha kesin bloklaniyor.

Test guvencesi:
- Guncellenen testler:
  - `tests/unit/test_pipeline_refactor_upgrade.py`
    - `test_taskspec_contract_blocks_empty_document_artifact`
    - `test_build_reflexion_hint_uses_job_profile`
    - `test_verify_gate_uses_taskspec_contract_and_appends_reflexion_hint`
- Calistirilan testler:
  - `python -m pytest -q tests/unit/test_pipeline_refactor_upgrade.py -k "taskspec_contract or reflexion_hint or verify_gate_blocks_completed_delivery_when_strict_flag_enabled or verify_gate_uses_taskspec_contract"` -> `4 passed`
  - `python -m pytest -q tests/unit/test_pipeline_refactor_upgrade.py tests/unit/test_task_spec_standard.py tests/unit/test_task_spec_validation.py tests/unit/test_pipeline_team_mode.py tests/unit/test_agent_routing.py tests/unit/test_world_model.py` -> `213 passed`

### 14.32 Deterministic Verify-Repair Loop (2026-03-11)

Roadmap uyumlu hedef:
- Faz 5'i bir adim daha ileri tasiyip verify fail oldugunda sadece hata yazan degil, uygun ise artifact'i deterministik olarak geri uretebilen bir loop kurmak.
- `done != verified` kuralini `repair -> revalidate` ile kapatmak.

Uygulanan degisiklikler:

1) TaskSpec replay tabanli repair eklendi
- `core/pipeline.py`
  - yeni helper: `_repair_taskspec_contract(...)`
  - sadece uygun failure siniflarinda calisir:
    - `deliverable:*`
    - `criteria:artifact_file_exists`
    - `criteria:artifact_file_not_empty`
    - `document:missing_artifact`
    - `document:empty_artifact`
  - `task_spec.steps` icindeki deterministik local adimlari replay eder:
    - `mkdir` -> `create_folder`
    - `write_file` -> `write_file`

2) Repair sonrasi state yenileme eklendi
- Repair basariliysa:
  - `ctx.tool_results` icine sentetik ama gercek artifact'e dayali sonuc yazilir
  - `ctx.intent["params"]["path"]` guncellenir
  - `produced_paths` yeniden hesaplanir
  - `verify_taskspec_contract(...)` tekrar calisir
  - `enforce_output_contract(...)` repair evidence ile tekrar calisir
- Boylece verify, capability runtime ve completion gate ayni gercek dunya durumunu gorur.

3) Completion/capability ile uyumlu kanit zinciri kuruldu
- File artifact repair sonrasi:
  - capability runtime artik `path_exists`, `non_empty`, `checksum_recorded` kapilarindan gecebilir
  - completion gate artik `missing_artifacts` ve `no_successful_tool_result` ile yanlis fail vermez
- `ctx.final_response` icine kontrollu bir dogrulama izi eklenir:
  - `Onarım sonrası doğrulandı: <path>`

4) Test harness duzeltildi
- `tests/unit/test_pipeline_refactor_upgrade.py`
  - yeni test:
    - `test_verify_gate_repairs_missing_document_artifact_via_taskspec_replay`
  - testte kullanilan `_RepairAgent` icin eksik `Path` importu eklendi

Neden kritik:
- Elyan artik verify fail oldugunda sadece “olmadi” demiyor.
- TaskSpec yeterince deterministikse artifact'i geri uretiyor, yeniden dogruluyor ve ancak sonra delivery aciyor.
- Bu, roadmap'teki `execute -> validate -> critique -> revise -> re-validate` loop'unun ilk gercek operasyonel hali.

Test guvencesi:
- `python -m pytest -q tests/unit/test_pipeline_refactor_upgrade.py::test_verify_gate_repairs_missing_document_artifact_via_taskspec_replay -vv` -> `1 passed`
- `python -m pytest -q tests/unit/test_pipeline_refactor_upgrade.py tests/unit/test_task_spec_standard.py tests/unit/test_task_spec_validation.py tests/unit/test_pipeline_team_mode.py tests/unit/test_agent_routing.py tests/unit/test_world_model.py` -> `214 passed`

### 14.33 Failure-Class Driven Recovery Gate (2026-03-11)

Roadmap uyumlu hedef:
- verify ve repair akisini yalnizca ad-hoc helper'lara degil, failure-class tabanli deterministic recovery politikasina baglamak
- "neden fail oldu?" sorusunu runtime kararina cevirmek

Uygulanan degisiklikler:

1) Recovery policy genisletildi
- `core/recovery_policy.py`
  - yeni strateji:
    - `replay_taskspec_artifact`
  - ne zaman secilir:
    - `failure_class == planning_failure`
    - action file/document teslim turlerinden biri
    - TaskSpec mevcut
    - failure nedenleri artifact/deliverable eksigine isaret ediyor

2) TaskSpec fail -> failure class -> recovery strategy zinciri eklendi
- `core/pipeline.py`
  - yeni helper:
    - `_classify_taskspec_failure(...)`
  - `StageVerify` artik:
    - TaskSpec verify fail'ini siniflandiriyor
    - `select_recovery_strategy(...)` ile deterministic recovery karari uretiyor
    - sonucu `ctx.qa_results` altina yaziyor:
      - `taskspec_failure`
      - `taskspec_recovery_strategy`
    - sadece recovery policy uygun gorurse `TaskSpec replay repair` calisiyor

3) Verify loop daha denetlenebilir hale geldi
- Sistem artik sadece "repair dene" demiyor.
- Once:
  - failure class
  - recovery strategy
  - sonra repair
  sirasiyla calisiyor.
- Bu, ileride code/research/browser recovery profillerini ayni mekanizmaya baglamayi kolaylastirir.

Neden kritik:
- Elyan'in recovery davranisi artik daha olculur ve daha genisletilebilir.
- Planner/validator/repair arasi "kural tabanli kopru" kurulmus oldu.
- Bu, roadmap'teki policy engine + fail diagnosis hedefinin dogrudan cekirdek parcasi.

Test guvencesi:
- `tests/unit/test_recovery_policy.py`
  - yeni test:
    - `test_recovery_policy_planning_failure_replays_taskspec_artifact`
- `tests/unit/test_pipeline_refactor_upgrade.py`
  - `test_verify_gate_repairs_missing_document_artifact_via_taskspec_replay`
    - artik recovery strategy ve failure class'i da assert ediyor
- Calistirilan testler:
  - `python -m pytest -q tests/unit/test_recovery_policy.py tests/unit/test_pipeline_refactor_upgrade.py -k "recovery_policy or repairs_missing_document_artifact or taskspec_contract or reflexion_hint"` -> `8 passed`
  - `python -m pytest -q tests/unit/test_pipeline_refactor_upgrade.py tests/unit/test_task_spec_standard.py tests/unit/test_task_spec_validation.py tests/unit/test_pipeline_team_mode.py tests/unit/test_agent_routing.py tests/unit/test_world_model.py tests/unit/test_recovery_policy.py` -> `218 passed`

### 14.34 Code Quality Recovery Contract (2026-03-11)

Roadmap uyumlu hedef:
- code_project gorevlerinde verify fail oldugunda sadece "eksik lint/test/typecheck" demek yerine, deterministic ve calistirilabilir bir quality-gate recovery contract uretmek
- profesyonel operator sisteminde code teslimlerinin kalite kapilarini explicit hale getirmek

Uygulanan degisiklikler:

1) Recovery policy'ye code quality strategy eklendi
- `core/recovery_policy.py`
  - yeni strateji:
    - `quality_gate_plan`
  - ne zaman secilir:
    - `failure_class == planning_failure`
    - code gate fail mevcut
    - quality gate command listesi belirlenebiliyor

2) Deterministic code repair plan builder eklendi
- `core/pipeline.py`
  - yeni helper:
    - `_build_code_quality_gate_plan(...)`
  - uretilen plan:
    - `stack`
    - `failed_gates`
    - `commands`
    - `repairable`
  - stack'e gore command uretir:
    - Python: `ruff check .`, `python -m pytest -q`, `mypy .`
    - Node/TS: `npm run lint`, `npm test -- --runInBand`, `npm run typecheck`
    - Go: `go vet ./...`, `go test ./...`
    - Rust: `cargo clippy -- -D warnings`, `cargo test`

3) StageVerify icinde code gate -> recovery strategy baglandi
- `core/pipeline.py`
  - code gate fail oldugunda:
    - `output_contract.signals.missing` ile `code_gate.failed` birlestirilir
    - `tests -> smoke` normalize edilir
    - deterministic repair plan uretilir
    - `select_recovery_strategy(...)` ile `quality_gate_plan` karari verilir
    - `ctx.qa_results` altina yazilir:
      - `code_failure`
      - `code_recovery_strategy`
      - `code_repair_plan`
  - final response'a kisa bir sonraki adim eklenir:
    - `Quality gate next: ...`

Neden kritik:
- Elyan code teslimlerinde artik sadece fail sinyali vermiyor; fail'i operasyonel bir sonraki adıma ceviriyor.
- Bu, "gorevleri dogrulayarak tamamlayan profesyonel AI calisma sistemi" hedefi icin gerekli cunku code output sadece dosya yazmak degil, kalite kapilarini kapatmak demek.
- Ileride bu planlar otomatik `run_safe_command` replay loop'una baglanabilir.

Test guvencesi:
- `tests/unit/test_recovery_policy.py`
  - yeni test:
    - `test_recovery_policy_planning_failure_builds_quality_gate_plan`
- `tests/unit/test_pipeline_refactor_upgrade.py`
  - yeni test:
    - `test_verify_stage_builds_code_quality_gate_recovery_plan`
- Calistirilan testler:
  - `python -m pytest -q tests/unit/test_recovery_policy.py tests/unit/test_pipeline_refactor_upgrade.py -k "quality_gate_plan or code_quality_gate_recovery_plan or recovery_policy or critic_role"` -> `7 passed`
  - `python -m pytest -q tests/unit/test_pipeline_refactor_upgrade.py tests/unit/test_task_spec_standard.py tests/unit/test_task_spec_validation.py tests/unit/test_pipeline_team_mode.py tests/unit/test_agent_routing.py tests/unit/test_world_model.py tests/unit/test_recovery_policy.py` -> `220 passed`

### 14.35 Research Recovery Contract (2026-03-11)

Roadmap uyumlu hedef:
- research gorevlerinde verify fail oldugunda sonucu yalnizca "kaynak eksik" diye bloklamak yerine deterministic bir revise plani uretmek
- profesyonel rapor/araştırma teslimlerini kaynak, claim map ve unknowns ekseninde denetlenebilir hale getirmek

Uygulanan degisiklikler:

1) Recovery policy'ye research strategy eklendi
- `core/recovery_policy.py`
  - yeni strateji:
    - `research_revision_plan`
  - ne zaman secilir:
    - `failure_class == planning_failure`
    - research gate fail mevcut
    - revise step listesi uretilmis

2) Deterministic research repair plan builder eklendi
- `core/pipeline.py`
  - yeni helper:
    - `_build_research_recovery_plan(...)`
  - uretilen plan:
    - `failed_gates`
    - `source_count`
    - `payload_errors`
    - `steps`
    - `repairable`
  - fail'e gore step uretir:
    - `sources` -> `En az 3 güvenilir kaynak ekle`
    - `claim_mapping` -> `Ana iddiaları kaynaklarla eşle`
    - `unknowns` -> `Belirsizlikler ve sınırlılıklar bölümü ekle`
    - `payload:*` -> `Yapısal research payload üret ve doğrula`

3) StageVerify icinde research gate -> recovery strategy baglandi
- `core/pipeline.py`
  - research gate veya research payload fail oldugunda:
    - combined failed gate listesi uretilir
    - deterministic research repair plan kurulur
    - `select_recovery_strategy(...)` ile `research_revision_plan` secilir
    - `ctx.qa_results` altina yazilir:
      - `research_failure`
      - `research_recovery_strategy`
      - `research_repair_plan`
  - final response'a kisa sonraki adim eklenir:
    - `Research next: ...`

Neden kritik:
- Elyan artık research teslimlerinde sadece “rapor eksik” demiyor; eksigi revizyon planına çeviriyor.
- Bu, arastirma/rapor akisini da operator seviyesine tasir cunku sistem eksigi tespit edip dogrudan hangi kalite katmaninin kapanacagini soyluyor.
- Bir sonraki asamada bu adimlar deterministic sub-agent gorevlerine cevrilebilir.

Test guvencesi:
- `tests/unit/test_recovery_policy.py`
  - yeni test:
    - `test_recovery_policy_planning_failure_builds_research_revision_plan`
- `tests/unit/test_pipeline_refactor_upgrade.py`
  - yeni test:
    - `test_verify_stage_builds_research_recovery_plan`
- Calistirilan testler:
  - `python -m pytest -q tests/unit/test_recovery_policy.py tests/unit/test_pipeline_refactor_upgrade.py -k "research_revision_plan or research_recovery_plan or quality_gate_plan or critic_review_prompt_for_research"` -> `4 passed`
  - `python -m pytest -q tests/unit/test_pipeline_refactor_upgrade.py tests/unit/test_task_spec_standard.py tests/unit/test_task_spec_validation.py tests/unit/test_pipeline_team_mode.py tests/unit/test_agent_routing.py tests/unit/test_world_model.py tests/unit/test_recovery_policy.py` -> `222 passed`

### 14.36 Existing Capability Hardening: App Control Parser (2026-03-11)

Karar:
- yeni feature eklenmiyor
- mevcut dogal dil + tool mapping kabiliyetleri sertlestiriliyor

Uygulanan sertlestirme:

1) Ultra-kisa app invocation destegi guclendirildi
- `core/intent_parser/_apps.py`
  - artik su tip mevcut ama zayif kalan ifadeler dogru parse ediliyor:
    - `safari a.`
    - `chrome'a`
    - `terminale`
  - bunlar `chat`e dusmek yerine `open_app`e gider

2) Focus komutlarinin reply kalitesi iyilestirildi
- `chrome'a geç`, `safariye geç` gibi mevcut komutlar zaten `open_app`e gidiyordu
- ama reply yanlis sekilde "aciliyor" diyordu
- artik odak/focus niyeti varsa reply:
  - `Google Chrome öne alınıyor...`
  seklinde doner

Neden kritik:
- Bu alan yeni capability degil; mevcut app control yeteneginin first-pass accuracy sertlestirmesi
- Kullanici kisa ve dogal cümle kurdugunda Elyan'in chat fallback'e dusmesini azaltiyor
- Ozellikle mobil/Telegram kullaniminda tek-kelimeye yakin komutlarda hata oranini dusurur

Test guvencesi:
- `tests/test_intent_parser_regressions.py`
  - yeni testler:
    - `test_ultra_short_app_invocation_routes_to_open_app`
    - `test_focus_phrase_uses_open_app_with_focus_reply`
- `tests/unit/test_intent_parser_and_dashboard.py`
  - yeni test:
    - `test_ultra_short_app_invocation_routes_to_open_app`
- Calistirilan testler:
  - `python -m pytest -q tests/test_intent_parser_regressions.py tests/unit/test_intent_parser_and_dashboard.py -k "ultra_short_app_invocation or focus_phrase or delete_desktop_screenshot_images"` -> `4 passed`
  - `python -m pytest -q tests/unit/test_pipeline_refactor_upgrade.py tests/unit/test_task_spec_standard.py tests/unit/test_task_spec_validation.py tests/unit/test_pipeline_team_mode.py tests/unit/test_agent_routing.py tests/unit/test_world_model.py tests/unit/test_recovery_policy.py tests/test_intent_parser_regressions.py tests/unit/test_intent_parser_and_dashboard.py` -> `284 passed`

### 14.37 Existing Capability Hardening: Tool Result Contract (2026-03-11)

Karar:
- yeni tool eklenmiyor
- mevcut tool'larin output payload'lari Faz 4 hedeflerine uygun sekilde daha standart hale getiriliyor

Uygulanan sertlestirme:

1) `file_tools` legacy payload'lari kontrata yaklastirildi
- `tools/file_tools.py`
  - `create_folder`
  - `delete_file`
- artik success payload'larinda standart alanlar var:
  - `status`
  - `message`
  - `retryable`
  - `data`
  - `output_path`
  - `artifacts`
- batch delete tarafinda ayrica:
  - `data.deleted_files`
  - `deleted_count`
  - `failed_count`

2) `system_tools` payload standardizasyonu eklendi
- `tools/system_tools.py`
  - `open_app`
  - `take_screenshot`
- artik bu tool'lar da standart alanlar donuyor:
  - `status`
  - `data`
  - `retryable`
  - `artifacts`
  - `output_path`
  - `warnings`

3) Legacy uyumluluk korundu
- mevcut call-site'lar kirilmasin diye eski alanlar korundu:
  - `success`
  - `path`
  - `size_bytes`
  - `verified`
  - `frontmost_app`
  - `deleted_count`
- yani degisiklik yeni feature degil, mevcut araclarin daha denetlenebilir output vermesi

Neden kritik:
- Faz 4'teki `tool result parser` hedefinin pratik karsiligi bu
- verify/capability/evidence katmanlari daha temiz ve daha tek tip output goruyor
- legacy tool ambiguity azaltiliyor
- sonraki adimda diger mevcut tool'lara da ayni output kontrati uygulanabilir

Test guvencesi:
- `tests/unit/test_file_tools_batch_delete.py`
  - yeni assertler:
    - `status`
    - `data.deleted_files`
  - yeni test:
    - `test_delete_file_standardized_payload_coerces_cleanly`
- `tests/unit/test_system_tools.py`
  - yeni assertler:
    - `status`
    - `data.app_name`
    - `coerce_tool_result(...)` ile screenshot artifact coercion
- Calistirilan testler:
  - `python -m pytest -q tests/unit/test_file_tools_batch_delete.py tests/unit/test_system_tools.py tests/unit/test_runtime_v3_contracts.py` -> `33 passed`
  - `python -m pytest -q tests/unit/test_pipeline_refactor_upgrade.py tests/unit/test_task_spec_standard.py tests/unit/test_task_spec_validation.py tests/unit/test_pipeline_team_mode.py tests/unit/test_agent_routing.py tests/unit/test_world_model.py tests/unit/test_recovery_policy.py tests/test_intent_parser_regressions.py tests/unit/test_intent_parser_and_dashboard.py tests/unit/test_file_tools_batch_delete.py tests/unit/test_system_tools.py tests/unit/test_runtime_v3_contracts.py` -> `317 passed`

### 14.38 Existing Capability Hardening: File Tool Contract Expansion (2026-03-11)

Karar:
- yeni feature eklenmiyor
- mevcut file tool zinciri Faz 4 hedeflerine gore ayni kontrata cekiliyor

Uygulanan sertlestirme:

1) `file_tools` standart payload kapsami genisletildi
- `tools/file_tools.py`
  - `list_files`
  - `read_file`
  - `write_file`
- bu tool'lar artik da su alanlari deterministik donuyor:
  - `status`
  - `message`
  - `data`
  - `output_path`
  - `artifacts`
  - `retryable`

2) Legacy alanlar korunuyor
- mevcut call-site uyumlulugu icin alanlar duruyor:
  - `items`
  - `count`
  - `content`
  - `size`
  - `bytes_read`
  - `bytes_written`
  - `sha256`
  - `preview_200_chars`
  - `created_files`

3) Contract coercion dogrulugu sertlestirildi
- `core/contracts/execution_result.py`
- artifact coercion artik `directory/dir/folder` tiplerini dogru sekilde `directory` olarak koruyor
- boylece `list_files` gibi tool'lar capability/runtime tarafinda dosya gibi degil dizin artifact'i olarak normalize ediliyor

Neden kritik:
- Faz 4'teki `tool result parser` ve `validator` katmanlari ancak artifact tipi dogruysa guvenilir calisir
- directory artifact'inin file'a dusmesi verify/runtime tarafinda yanlis evidence uretirdi
- mevcut file ops zincirinin first-pass contract dogrulugu arttirildi

Test guvencesi:
- `tests/unit/test_agent_contracts.py`
  - yeni testler:
    - `test_list_files_returns_standardized_payload_and_coerces`
    - `test_read_file_returns_standardized_payload_and_coerces`
  - guclendirilen test:
    - `test_write_file_returns_contract_metadata`
- Calistirilan testler:
  - `python -m pytest -q tests/unit/test_agent_contracts.py tests/unit/test_file_tools_batch_delete.py tests/unit/test_system_tools.py tests/unit/test_runtime_v3_contracts.py` -> `48 passed`

### 14.39 Existing Capability Hardening: File Ops Post-Check Reliability (2026-03-11)

Karar:
- yeni feature eklenmiyor
- mevcut file operation path'lerinde hiz, dogruluk ve verify edilebilirlik arttiriliyor

Uygulanan sertlestirme:

1) `search_files` deterministic ve contract-friendly hale getirildi
- `tools/file_tools.py`
- artik:
  - gecersiz dizin erken fail olur
  - `matches` sirali doner
  - standart alanlar korunur:
    - `status`
    - `data`
    - `output_path`
    - `artifacts`
    - `retryable`

2) `move_file` icin post-check verify eklendi
- tasima sonrasi:
  - hedef gercekten olusmus mu
  - kaynak beklenen sekilde kaybolmus mu
- hedef zaten varsa islem deterministic fail olur; sessiz overwrite yapilmaz

3) `copy_file` icin post-check verify eklendi
- kopyalama sonrasi:
  - hedef gercekten olusmus mu
  - kaynak korunmus mu
- hedef zaten varsa deterministic fail olur

4) `rename_file` icin post-check verify eklendi
- yeniden adlandirma sonrasi:
  - yeni yol var mi
  - eski yol kayboldu mu

Neden kritik:
- "tool success" ile "gercek islem basarisi" ayni sey degil
- bu sertlestirme Faz 4 + Faz 5 arasindaki dogruluk boslugunu kapatir
- dosya operasyonlarinda sessiz overwrite, stale path ve eksik verify kaynakli yanlis basari durumlari azaltilir

Test guvencesi:
- `tests/unit/test_agent_contracts.py`
  - yeni testler:
    - `test_search_files_returns_sorted_standardized_payload`
    - `test_move_file_returns_verified_standardized_payload`
    - `test_copy_file_returns_verified_standardized_payload`
    - `test_rename_file_returns_verified_standardized_payload`
- Calistirilan testler:
  - `python -m pytest -q tests/unit/test_agent_contracts.py` -> `19 passed`

### 14.40 Existing Capability Hardening: Chat Brevity + Internal Prompt Leak Guard (2026-03-11)

Karar:
- yeni feature eklenmiyor
- mevcut sohbet akisi daha kisa, daha dogal ve daha temiz hale getiriliyor

Uygulanan sertlestirme:

1) Selamlasma fast-path'e alindi
- `core/llm_client.py`
- `selam`, `merhaba` gibi saf greeting mesajlari artik LLM'e gitmeden hizli cevap veriyor
- bu sayede:
  - daha hizli doner
  - daha kisa doner
  - gereksiz uzun aciklamaya kaymaz

2) Chat output sanitizer eklendi
- `core/llm_client.py`
- kullaniciya giden sohbet cevabindan su tip ic metinler temizleniyor:
  - `Deliverable Spec:`
  - `Done Criteria:`
  - `Success Criteria:`
- boylece sistem ici plan/kontrat satirlari kullaniciya sizmaz

3) Selamlama tonu kisaltildi
- `core/response_tone.py`
- greeting suffix'leri daha kisa ve daha samimi hale getirildi:
  - `Nasıl yardımcı olayım?`
  - `Ne yapalım?`
  - `Buradayım.`
  - `Dinliyorum.`

4) Prompt ornegi de sadeleştirildi
- `core/prompt_templates.py`
- chat ornegi daha kisa hale getirildi

Neden kritik:
- kullanici algisinda en hizli bozulan sey gereksiz uzun ve robotik cevap
- ayrica ic prompt/plan satirlarinin sizmasi profesyonellik kaybi yaratir
- bu degisiklik mevcut sohbet kabiliyetini daha dogal ve daha guvenilir hale getirir

Test guvencesi:
- `tests/test_llm_router.py`
  - yeni testler:
    - `test_chat_greeting_shortcuts_without_provider_call`
    - `test_chat_sanitizes_internal_planning_markers`
- Calistirilan testler:
  - `python -m pytest -q tests/test_llm_router.py tests/unit/test_llm_client_profile_prompt.py` -> `10 passed`
  - genis regresyon paketi -> `346 passed`

### 14.41 Existing Capability Hardening: Gateway Chat Path Brevity Fix (2026-03-11)

Problem:
- `LLMClient.chat()` kisaltilsa bile gateway uzerinden gelen sohbetlerin bir kismi `core/agent.py` icindeki ayri `chat/respond/answer` path'ine gidiyordu
- bu nedenle restart sonrasi bile uzun/robotik greeting cevabi gorulebiliyordu

Uygulanan sertlestirme:

1) Agent-level fast greeting guard eklendi
- `core/agent.py`
- `chat/respond/answer` path'inde greeting tespit edilirse LLM'e gitmeden kisa cevap donuyor

2) Agent-level chat sanitizer eklendi
- `core/agent.py`
- kullaniciya gitmeden once sohbet cevabindan su satirlar temizleniyor:
  - `Deliverable Spec:`
  - `Done Criteria:`
  - `Success Criteria:`

3) Fallback chat da ayni davranisa cekildi
- LLM hazir degilse bile `selam` gibi mesajlar artik:
  - kisa
  - dogal
  - sistem ici metin sızdırmayan
  cevap donuyor

Neden kritik:
- onceki fix sadece `LLMClient.chat()` yolunu temizliyordu
- bu patch gercek gateway runtime path'ini de kapsayarak kullaniciya yansiyan davranisi duzeltiyor

Test guvencesi:
- yeni test dosyasi:
  - `tests/unit/test_agent_chat_hardening.py`
- testler:
  - `test_agent_fast_chat_reply_shortcuts_greeting`
  - `test_agent_sanitize_chat_reply_strips_internal_markers`
- Calistirilan testler:
  - `python -m pytest -q tests/unit/test_agent_chat_hardening.py tests/test_llm_router.py tests/unit/test_llm_client_profile_prompt.py` -> `12 passed`
  - genis regresyon paketi -> `348 passed`

### 14.42 Existing Capability Hardening: Natural Small-Talk Coverage (2026-03-11)

Problem:
- sistem sadece `selam` benzeri greeting'leri kisaltinca bu kez `naber`, `napıosun`, `ne yapıyorsun` gibi dogal konusma varyasyonlari fazla jenerik cevaba dusuyordu

Uygulanan sertlestirme:

1) Fast-response small-talk kapsami genisletildi
- `core/fast_response.py`
- yeni/guclenen varyasyonlar:
  - `naber`
  - `nasılsın`
  - `napıosun`
  - `napiosun`
  - `napiyosun`
  - `ne yapıyorsun`

2) Dogal cevap havuzu sade ve kisa tutuldu
- ornek cevaplar:
  - `İyiyim, sen nasılsın?`
  - `Buradayım, seni dinliyorum.`
  - `Seninleyim. Ne lazım?`
  - `Hazırım, söyle.`

Neden kritik:
- kullanici sadece komut vermiyor; kisa dogal konusma da yapiyor
- bu alan zayif kalirsa Elyan ya robotik gorunur ya da yanlis greeting cevabina duser

Test guvencesi:
- yeni test dosyasi:
  - `tests/unit/test_fast_response.py`
- testler:
  - `test_fast_response_handles_naber_naturally`
  - `test_fast_response_handles_colloquial_what_are_you_doing`
- Calistirilan testler:
  - `python -m pytest -q tests/unit/test_fast_response.py tests/unit/test_agent_chat_hardening.py tests/test_llm_router.py` -> `10 passed`
  - genis regresyon paketi -> `376 passed`

### 14.43 Existing Capability Hardening: Turkish NLU Normalization Layer (2026-03-11)

Karar:
- yeni feature eklenmiyor
- dogal dil anlama cekirdegi ortak normalize katmani ile sertlestiriliyor

Uygulanan sertlestirme:

1) Ortak Turkish NLU normalizer eklendi
- `core/nlu_normalizer.py`
- su sinif problemleri tek yerde normalize ediliyor:
  - typo
  - argo kisaltma
  - apostrof varyasyonlari
  - ekli yazimlar
  - ascii fold

2) Normalizer parser girisine baglandi
- `core/intent_parser/_base.py`
- parser `text_norm` artik sadece harf donusumu degil, typo/argo normalize da goruyor

3) Normalizer quick-intent katmanina baglandi
- `core/quick_intent.py`
- `napıosun`, `mrb`, `chromea geç` gibi varyasyonlar daha erken dogru route oluyor
- ek olarak dogrudan chat phrase shortcut eklendi:
  - `naber`
  - `nasılsın`
  - `ne yapıyorsun`
  - `elyan`

4) Normalizer fast-response katmanina baglandi
- `core/fast_response.py`
- selamlama ve small-talk hizli cevaplari typo/argo girdilerde de calisiyor

Neden kritik:
- ayni kullanici niyeti farkli yazimlarla geldigi halde farkli path'lere dusmemeli
- tek tek her parser'a typo yamasi eklemek yerine ortak NLU preprocessing daha dogru ve daha hizli

Test guvencesi:
- yeni test dosyasi:
  - `tests/unit/test_nlu_normalizer.py`
- ek parser regresyonu:
  - `tests/test_intent_parser_regressions.py::test_typo_focus_phrase_normalizes_to_open_app`
- Calistirilan testler:
  - `python -m pytest -q tests/unit/test_nlu_normalizer.py tests/unit/test_fast_response.py tests/test_intent_parser_regressions.py -k 'normalizer or typo_focus_phrase or naber or colloquial'` -> `7 passed`
  - genis regresyon paketi -> `384 passed`
### 14.44 Existing Capability Hardening: Unified Turkish NLU Decision Path

- Problem:
  - normalize katmani parser ve fast-response tarafinda varken `agent` kararlarinin bir kismi ve `fuzzy_intent` hala kendi lokal normalize mantigi ile calisiyordu
  - bu da ayni cumlenin farkli path'lerde farkli yorumlanmasina yol aciyordu
  - ozellikle `fatih terim kimdir`, `napıosun`, `chromea geç`, `safariyi aç` gibi Turkce varyasyonlar soru/sohbet/komut ayriminda tutarsizdi

- Gelistirme:
  - `core/nlu_normalizer.py`
    - ek yapismis yaygin Turkce sonekler icin genel split mantigi eklendi
    - ornekler:
      - `chromea` -> `chrome a`
      - `safariyi` -> `safari yi`
      - `terminalde` -> `terminal de`
  - `core/fuzzy_intent.py`
    - legacy `normalize_turkish()` artik once ortak `normalize_turkish_text()` kullaniyor
    - yani fuzzy matcher da parser ve quick-intent ile ayni normalize tabanina yaslaniyor
  - `core/agent.py`
    - `_is_information_question`, `_is_likely_chat_message`, `_is_creative_writing_request`
      artik ortak Turkce normalize katmani uzerinden calisiyor
    - boylece chat/soru/komut ayrimi daha tutarli hale geldi

- Beklenen Etki:
  - bilgi sorulari onceki mesajlara veya chat fallback'ine daha az sapar
  - ek yapismis Turkce komutlar daha iyi anlasilir
  - ayni kullanici ifadesi hangi path'ten gecerse gecsin daha benzer siniflandirilir

### 14.45 Existing Capability Hardening: Multi-Step Turkish Connector Parsing

- Problem:
  - `açıp`, `çalıştırıp`, `girip`, `gidip`, `yazıp` gibi Turkce baglacli komutlar bazi path'lerde tek adim gibi algilaniyordu
  - bu da ozellikle terminal ve browser komutlarinda sirali gorevlerin kacmasina neden oluyordu

- Gelistirme:
  - `core/nlu_normalizer.py`
    - `googlea`, `youtubea` gibi yapisik sonekler normalize edildi
    - `acip`, `calistirip`, `yazip` gibi ascii varyasyonlar Turkce forma cekildi
  - `core/agent.py`
    - `_split_multi_step_text()` artik `açıp / çalıştırıp / gidip / girip / yazıp` baglaclarini cok-adim ayirici olarak kullaniyor
    - `_extract_terminal_command_from_text()` bu baglaclari komut govdesinden temizliyor
  - `core/intent_parser/__init__.py`
    - parser-level multi-step splitter ayni baglaclarla genisletildi
  - `core/intent_parser/_apps.py`
    - terminal command parser baglac kalintilarini komut basindan temizliyor

- Beklenen Etki:
  - `terminal açıp elyan restart komutunu çalıştır` daha dogru sekilde `open_app + type_text` planina doner
  - `chrome dan yeni sekme açıp ...` gibi browser akislari daha az tek-adimda kaybolur

### 14.46 Existing Capability Hardening: Memory-Driven NLU Alias + Batch Delete Inference

- Problem:
  - kullanicinin kendi yazim aliskanliklari sistem tarafinda kalici olarak NLU'ya beslenmiyordu
  - bu nedenle `ggl`, `chrma`, benzeri kisisel kisaltmalar her seferinde ayni sekilde ogrenilmiyordu
  - `Masaüstündeki ekran resimlerini sil` gibi dogal ama toplu hedef anlatan komutlar da gereksiz netlestirmeye dusebiliyordu

- Gelistirme:
  - `core/agent.py`
    - yeni `_runtime_normalize_user_input()` katmani eklendi
    - mevcut normalize adimina ek olarak `learning.get_preferences()` icinden:
      - `nlu_aliases`
      - `phrase_aliases`
      - `user_nlu_aliases`
      haritalarini okuyup regex tabanli alias genisletme yapiyor
    - bu normalize edilmis metin pipeline context ve run-store yaziminda kullaniliyor
  - `core/agent.py`
    - yeni `_infer_batch_delete_patterns()` yardimcisi eklendi
    - `ekran resmi / ekran görüntüsü / screenshot / screen shot` varyasyonlarini tespit ediyor
    - `delete_file` icin guvenli batch payload uretiyor:
      - `directory`
      - `patterns`
      - `max_files`
      - `force=False`
  - `core/agent.py`
    - `delete_file` param hazirlama hattinda batch-pattern mode ayri ele alindi
    - tek dosya yolu zorlamadan toplu silme senaryolari daha dogru hazirlaniyor

- Beklenen Etki:
  - Elyan kullanicinin kisaltma ve yazim aliskanliklarini daha iyi ogrenerek daha tutarli anlar
  - `Masaüstündeki ekran resimlerini sil` gibi komutlar gereksiz netlestirmeye daha az duser
  - batch delete niyeti daha kontrollu, daha denetlenebilir payload ile execution katmanina iner

- Calistirilan testler:
  - `python -m pytest -q tests/unit/test_agent_routing.py -k 'batch_delete_screenshot_images or runtime_normalize_user_input_applies_learned_aliases or infer_general_tool_intent_uses_last_path_for_pronoun_delete'` -> `3 passed`
  - `python -m pytest -q tests/unit/test_nlu_normalizer.py tests/unit/test_agent_routing.py tests/test_intent_parser_regressions.py` -> `183 passed`

### 14.47 Existing Capability Hardening: Research Delivery Output Discipline

- Problem:
  - research/document akisi kullanici tek bir duzenli Word belgesi beklerken `.md + .txt + docx (+ bazen ek report copies)` uretiyordu
  - `research_document_delivery` sonucu icindeki `summary` alanı da dogrudan chat renderer'a dusuyor ve kullanıcıya gereksiz uzun, ham arastirma metni donuyordu
  - varsayilan cikti secimi de fazla agresifti; acikca istenmese bile `excel` acilabiliyordu

- Gelistirme:
  - `core/intent_parser/_research.py`
    - research delivery varsayilani `word-only` olacak sekilde duzeltildi
    - explicit `excel/xlsx/tablo/csv` yoksa `include_excel=False`
  - `core/agent.py`
    - general intent ve skill fallback tarafinda research document varsayilani `include_word=True`, `include_excel=False` olarak sertlestirildi
    - `_render_research_result()` artik `research_document_delivery` sonucunu ham summary olarak degil, kisa artifact cevabi olarak render ediyor
  - `tools/pro_workflows.py`
    - `research_document_delivery()` artik sadece kullanicinin istedigi artifactleri uretir
    - `include_word=True, include_excel=False` senaryosunda tek `.docx` sonuc dondurur
    - eski `.md/.txt` pack davranisi sadece office output hic istenmemisse markdown fallback olarak kalir
    - `report_paths` gibi yan urunler artik `outputs` yerine `supporting_artifacts` altina alinir
    - Word icerigi icin yeni temizleme/sentez katmani eklendi:
      - bulgulardan `Kaynak/Güven` kuyruklarini ayiklar
      - gereksiz `Operasyonel Oneriler / Sinirliliklar / devam adimi` govdesini ozetten tasimaz
      - daha duzenli bolumler uretir: `Kisa Ozet`, `Talep Cercevesi`, `Temel Bulgular`, `Kaynak Degerlendirmesi`, `Sonuc`

- Beklenen Etki:
  - `fourier denklem araştır` gibi isteklerde coklu markdown artefact sacilmasi azalir
  - tek Word belgesi istenen akislarda kullaniciya tek bir ana output verilir
  - chat cevabi arastirma dump'i yerine kisa ve kullanilabilir bir teslim mesaji olur
  - research/document hattinda `format dogrulugu` ve `artifact disiplini` artar

- Calistirilan testler:
  - `python -m pytest -q tests/test_intent_parser_regressions.py tests/unit/test_agent_routing.py tests/unit/test_pro_workflows.py -k 'research_document_delivery or research_prompt_defaults_to_document_delivery or renders_research_document_delivery_concisely'` -> `7 passed`
  - `python -m pytest -q tests/test_intent_parser_regressions.py tests/unit/test_agent_routing.py tests/unit/test_pro_workflows.py tests/unit/test_capability_router.py tests/integration/test_intent_to_tool_pipeline.py` -> `212 passed`

### 14.48 Existing Capability Hardening: Format-Aware Document Delivery

- Problem:
  - `generate_document_pack` tek bir istekten gereksiz `.md/.txt/action register/risk register` paketi uretiyordu
  - `pdf` istendiginde bile `rapor/belge` kelimesi yuzunden `word` de eklenebiliyordu
  - Word icerigi halen fazla meta-baslikliydi; kullanici sadece duzgun arastirma metni isterken belgeye sistemik basliklar ve guven ibareleri girebiliyordu

- Gelistirme:
  - `tools/pro_workflows.py`
    - yeni format cikarim yardimcilari eklendi:
      - `_infer_requested_document_formats()`
      - `_build_plain_document_text()`
      - `_build_excel_document_payload()`
      - `_write_simple_pdf()`
    - `generate_document_pack()` artik varsayilan olarak `tek docx` uretir
    - explicit format isteklerinde yalnizca istenen format(lar)i uretir:
      - `word/docx`
      - `excel/xlsx/csv/tablo`
      - `pdf`
      - gerekirse `md/txt`
    - `research_document_delivery()` artik `include_pdf` destekliyor
    - research Word/PDF govdesi sade metne cekildi; `Yonetici Ozeti / Operasyonel Oneriler / Guven` gibi ham arastirma dump'lari belge icinden temizlendi
  - `core/agent.py`
    - research delivery format cikarma mantigi sertlestirildi
    - `pdf` istegi varsa generic `rapor/belge` marker'i artik otomatik `word` acmiyor
    - `generate_document_pack` icin `preferred_formats` tool param hazirlama eklendi
  - `core/intent_parser/_research.py`
    - parser tarafinda da `pdf` explicit istek olarak ayrildi
    - varsayilan research delivery davranisi `word-only`, `pdf-only` ve `excel-only` catismasiz hale getirildi

- Beklenen Etki:
  - kullanici `tek bir word belgesi`, `pdf`, `excel` dediginde Elyan buna daha sadik kalir
  - belge icerigi daha sade, daha kullanisli ve daha az sistemik jargon tasir
  - `rapor` kelimesi artik otomatik coklu artifact uretimine daha az neden olur
  - document generation tarafi `format dogrulugu + icerik sadeligi` acisindan daha guvenilir hale gelir

- Calistirilan testler:
  - `python -m pytest -q tests/test_intent_parser_regressions.py tests/unit/test_agent_routing.py tests/unit/test_pro_workflows.py -k 'research_document_delivery or generate_document_pack or prefers_pdf or defaults_to_single_docx or pdf_only or defaults_to_word_only or parser_extracts_inline_content or excel_parser_extracts_headers_and_content'` -> `12 passed`
  - `python -m pytest -q tests/test_intent_parser_regressions.py tests/unit/test_agent_routing.py tests/unit/test_pro_workflows.py tests/unit/test_capability_router.py tests/integration/test_intent_to_tool_pipeline.py` -> `217 passed`

### 14.49 Existing Capability Hardening: Reliable Word/PDF/Excel Creation

- Problem:
  - Word olusturma runtime'da fiilen calismiyordu; aktif venv icinde `python-docx` ve `reportlab` yoktu
  - `research_document_delivery()` belge olusturulamasa bile `success=true` donup sadece klasor yolunu `path` diye veriyordu
  - `advanced_research()` arka planda zorunlu hizli `.md` raporu yaziyor, kullanici tek Word istese bile yan artifact uretiyordu
  - belge govdesi zaman zaman komut cumlesini veya `Yonetici Ozeti / Ana Bulgular / Kaynak Politikasi` gibi meta satirlari dogrudan belgeye tasiiyordu
  - planner research delivery icin tekrar `include_excel=True` varsayimina kaymisti

- Gelistirme:
  - runtime bagimliliklari aktif ortama kuruldu:
    - `python-docx`
    - `reportlab`
    - `openpyxl`
  - `tools/research_tools/advanced_research.py`
    - `persist_quick_report` parametresi eklendi
    - research delivery path'i artik gizli markdown elden cikarmak istemiyorsa `.md` raporu zorunlu yazmiyor
  - `tools/pro_workflows.py`
    - `research_document_delivery()` artik `deliver_copy` parametresini kabul ediyor; tool signature/runtime drift kapatildi
    - advanced research cagrisi icinde `generate_report=False` ve `persist_quick_report=deliver_copy` yapildi
    - istenen Word/PDF/Excel artifact olusmazsa tool artik `success=false` donuyor; sessiz bos basari yok
    - command-like brief temizleme ve belge govdesi zenginlestirme eklendi
    - research Word govdesine ikinci scrub katmani eklendi; `Yonetici Ozeti`, `Ana Bulgular`, `Kaynak Politikasi`, `guvenilirlik` gibi meta satirlar belgeye girmiyor
  - `core/intelligent_planner.py`
    - `research_document_delivery` varsayilaninda `include_excel=False` yapildi; planner/runtime drift kapatildi

- Beklenen Etki:
  - Elyan tek Word istendiginde gercek `.docx` olusturur
  - belge olusmadiysa bunu basari gibi sunmaz
  - research delivery altinda kullanicidan gizli `.md` yan rapor sızmaz
  - Word govdesi daha sade ve kullaniciya donuk kalir; operasyonel/meta dump tasimaz

- Calistirilan testler:
  - `python -m pytest -q tests/unit/test_pro_workflows.py tests/unit/test_agent_routing.py tests/unit/test_professional_stabilization.py` -> `169 passed`
  - izole runtime dogrulamasi:
    - `write_word()` -> gercek `.docx` olustu
    - `research_document_delivery('fourier denklem', word-only)` -> tek `.docx`, `supporting_artifacts=[]`

### 14.50 Existing Capability Hardening: Cleaner Research Document Body

- Problem:
  - Word belgesi artik olusuyordu fakat arastirma govdesi hala dusuk degerli bulgulari oldugu gibi tasiyabiliyordu
  - `youtube/video`, `Denklem 1`, `Sekil`, soru/video basligi gibi satirlar metni kirletiyordu
  - summary temizlense bile belge govdesi bazen ham bulgu listesine fazla bagimli kaliyor ve metin akisi bozuluyordu

- Gelistirme:
  - `tools/pro_workflows.py`
    - `_is_low_value_research_statement()` eklendi
    - `_select_research_document_findings()` eklendi
    - research Word/PDF/Excel delivery artik ayni temiz bulgu secimini kullaniyor
    - dusuk degerli satirlar belgeye alinmiyor:
      - youtube/video referanslari
      - `Denklem 1/2/3` etiketli satirlar
      - `Sekil`/formula odakli ham UI-benzeri satirlar
      - kaynak/güven annotation dump'lari
    - intro bos veya kirli gelirse sade bir fallback arastirma girisi yaziliyor
  - `tests/unit/test_pro_workflows.py`
    - belge govdesinde `BUders`, `Denklem 1`, `Yonetici Ozeti`, `Ana Bulgular`, `Kaynak Politikasi` gibi kirli satirlarin bulunmamasi testle sabitlendi

- Beklenen Etki:
  - research Word/PDF govdesi daha okunur olur
  - ham arastirma dump'i yerine kullaniciya uygun anlatim kalir
  - Excel de daha temiz bulgu satirlariyla dolar

- Calistirilan testler:
  - `python -m pytest -q tests/unit/test_pro_workflows.py` -> `15 passed`
  - gercek runtime dogrulamasi:
    - `fourier denklem` word-only delivery tekrar kosuldu
    - tek `.docx` olustu
    - govdede `youtube`, `Denklem 1`, meta-baslik sızıntisi gorulmedi

### 14.51 Existing Capability Hardening: LLM-backed Research Synthesis + LaTeX

- Problem:
  - research delivery belgeyi olustursa bile metin buyuk oranda heuristik sentezden geliyordu
  - bagli LLM provider'lari aktif olsa bile research belge govdesi bunlardan yararlanmiyordu
  - `latex/.tex` format istegi belge hattinda resmi olarak desteklenmiyordu
  - Google provider parser'i `candidates` anahtarina kor bagliydi; fallback zincirinde gereksiz kiriliyordu

- Gelistirme:
  - `tools/pro_workflows.py`
    - `_synthesize_research_body_with_llm()` eklendi
    - research delivery artik temiz bulgu + secilmis kaynaklari `research_worker` role'u ile LLM'e verip konuya odakli govde yazdirmayi deniyor
    - LLM unusable ise heuristik fallback devam ediyor; kor bos basari yok
    - `latex/.tex` formati hem genel document pack hem research delivery icin desteklendi
    - kaynak secimi sertlestirildi; dusuk degerli domainler ve zayif kaynaklar belge govdesinde daha az yer buluyor
  - `core/intent_parser/_research.py`
    - `latex` / `tex` istekleri `include_latex` olarak parse ediliyor
  - `core/agent.py`
    - research delivery ve document pack format hazirlama hattina `latex` eklendi
  - `core/llm_client.py`
    - Gemini parser'i sertlestirildi; invalid response durumunda anlamli hata verip fallback'e izin veriyor
  - runtime
    - `openai` SDK aktif ortama kuruldu; API key varsa provider artik dogrudan kullanilabilir

- Beklenen Etki:
  - research Word govdesi konuya daha yakin ve daha dogal olur
  - bagli local/API LLM'ler research sentezinde gercekten kullanilir
  - `latex` isteyen kullanici tek `.tex` artifact alabilir

- Calistirilan dogrulamalar:
  - gercek runtime: `fourier denklem` word-only delivery tekrar kosuldu
  - LLM trace: `ollama -> openai` fallback zinciri goruldu; belge govdesi model senteziyle genisledi

### 14.52 Existing Capability Hardening: Topic-Aware Research Search Quality

- Problem:
  - research sentezi daha iyi hale gelse de upstream source pool bazen zayif blog/video agirlikli kalabiliyordu
  - tek sorgulu arama matematik/teknik konularda zayifti; `formula`, `proof`, `pdf lecture notes` gibi niyetler arama planina girmiyordu
  - bu da belge govdesinin konuya yeterince derin baglanmamasina neden oluyordu

- Gelistirme:
  - `tools/research_tools/advanced_research.py`
    - low-value domain listesi sertlestirildi:
      - `blog.`
      - `youtube.com`
      - `youtu.be`
    - matematik/denklem/fourier gibi konular icin query decomposition zenginlestirildi:
      - `definition`
      - `formula`
      - `proof`
      - `applications`
      - `pdf lecture notes`
      - `university notes`
    - `_perform_topic_web_search()` eklendi; artik tek sorgu yerine konuya gore coklu sorgu merge + rerank yapiliyor
    - advanced research ana akisi bunu kullanmaya cekildi

- Beklenen Etki:
  - teknik ve matematik konularinda MIT/Purdue/university PDF gibi kaynaklarin ust siraya gelme sansi artar
  - blog/video tabanli zayif kaynaklar belge sentezine daha az girer
  - research govdesi daha konuya bagli ve daha profesyonel olur

- Calistirilan dogrulamalar:
  - `python -m pytest -q tests/unit/test_pro_workflows.py` -> temiz
  - canli Fourier ornegi:
    - source pool icinde `MIT OCW` ve `Purdue` PDF goruldu
    - `youtube` sonucu ust deliverable source listesine girmedi

### 14.53 Existing Capability Hardening: Dashboard IA Refresh + LLM/Profile Control

- Problem:
  - dashboard tek ekranda cok fazla panel gosterdigi icin daginikti
  - bagli LLM'leri yonetme ve fallback/default durumu net gorunmuyordu
  - agent kisisellestirme dashboard uzerinden duzenlenemiyordu
  - arayuz asset'leri ile backend profile/model endpoint'leri arasinda urun seviyesi bag eksikti

- Gelistirme:
  - `ui/web/dashboard.html`
    - dashboard 4 sekmeli bilgi mimarisine ayrildi:
      - `Genel Bakis`
      - `LLM Yonetimi`
      - `Kisisellestirme`
      - `Operasyon`
    - mevcut task/workflow/model panelleri korunup daha temiz bolumlere dagitildi
    - yeni profile editor alanlari eklendi:
      - agent adi
      - dil
      - kisilik
      - yanit modu
      - yanit uzunlugu
      - local-first
      - autonomous
      - system prompt
  - `ui/web/dashboard.css`
    - dashboard layout ve responsive davranis yeniden duzenlendi
    - daha okunur kart hiyerarsisi ve sekmeli navigasyon eklendi
  - `ui/web/dashboard.js`
    - `/api/agent/profile` veri akisi dashboard'a baglandi
    - model summary/fallback/provider-key gorunumu eklendi
    - registry satirlarina `fallback yap` aksiyonu eklendi
    - profile save akisi eklendi
  - `core/gateway/server.py`
    - `handle_agent_profile_get()` artik `user_profile` ozetini de donuyor
    - `handle_agent_profile_update()` artik `response_length_bias` ve local profile tercihlerini persist ediyor

- Beklenen Etki:
  - dashboard uretim kullanimi icin daha temiz ve yonetilebilir hale gelir
  - bagli LLM havuzu, varsayilan model ve fallback daha net gorunur
  - kullanici Elyan'in cevap stilini ve kisilik ayarlarini panelden degistirebilir

- Calistirilan dogrulamalar:
  - `pytest tests/unit/test_dashboard_html.py tests/unit/test_dashboard_assets.py tests/unit/test_gateway_server_message.py -q` -> temiz
  - `gateway restart --daemon` sonrasi `/api/agent/profile` ve `/api/models` canli kontrol edildi

### 14.54 Existing Capability Hardening: Manifest Attachment Discipline

- Problem:
  - bazi cevaplarda `manifest.json` kullanici istemeden otomatik ek olarak gidiyordu
  - bu hem gereksiz gürültü üretiyor hem de belge/cevap teslimini bozuyordu
  - gateway, envelope icindeki `evidence_manifest_path` alanini kosulsuz attach edebiliyordu

- Gelistirme:
  - `core/agent.py`
    - `_should_share_manifest()` artik aksiyona bakip otomatik `True` donmuyor
    - manifest sadece su durumlarda paylasiliyor:
      - kullanici acikca isterse
      - `requires_evidence=True` ise
      - runtime policy bunu acikca isterse
    - agent response metadata icine `share_manifest` bayragi eklendi
  - `core/gateway/router.py`
    - `evidence_manifest_path` artik sadece `metadata.share_manifest=True` ise attachment olarak ekleniyor
  - `core/runtime_policy.py`
    - strict preset dahil varsayilan manifest paylasimi kapali tutuldu

- Beklenen Etki:
  - kullanici istemeden `manifest.json` veya benzeri bos/gereksiz teknik dosyalar gonderilmez
  - belge ve cevap teslimi daha temiz kalir

- Calistirilan dogrulamalar:
  - `pytest tests/unit/test_agent_routing.py::test_agent_should_share_manifest_only_when_requested_or_required tests/unit/test_gateway_router.py::TestGatewayRouter::test_handle_incoming_message_does_not_attach_manifest_without_explicit_share_flag tests/unit/test_runtime_policy.py -q` -> temiz
  - `gateway restart --daemon` sonrasi health kontrolu -> temiz
