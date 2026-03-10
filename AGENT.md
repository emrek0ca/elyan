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
