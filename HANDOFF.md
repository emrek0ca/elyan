# Elyan Mac — Devir Notu (2026-07-08)

Amaç: Elyan macOS uygulamasını Jarvis gibi çalıştırmak — komutları anlayıp
masaüstünde gerçekten yürüten, sunucu beyniyle yalnız JSON veri sözleşmesiyle
konuşan bir agent.

## Mimari (mevcut hal)

- **Swift app** (`apps/macos/ElyanMac/`) → `RuntimeBridgeSwift` ile Python alt
  sürecini (`runtime/bridge.py`, stdin/stdout JSON) yönetir.
- **Komut akışı (yerel-öncelikli)**: mesaj önce yerel runtime'da çalışır
  (`conversation.send`) → deterministik router (`runtime/task_router.py`) →
  eşleşmezse yapılandırılmış planlayıcı (`runtime/structured_planner.py`,
  sözleşme: `elyan.plan.v1`) sunucu beynine JSON zarf gönderir → dönen plan
  doğrulanır → **yürütme daima masaüstünde** (`runtime/executor_core.py`,
  adımlar arası `_previousOutput/_previousResult` veri akışı var).
- Bridge çalışmıyorsa Swift eski bulut yoluna düşer (ChatStore.send fallback).

## Bu oturumlarda yapılanlar

1. **Router güçlendirme** (`task_router.py`): istek kipi normalizasyonu
   ("açar mısın/lütfen"), "X'e git/gir" site rotası (`_KNOWN_SITES`),
   "belgele/dökümante et/rapora dönüştür" → document_write (eskiden shell_run'a
   kaçıyordu!), "hakkında bilgi topla" → web_research.
   Testler: `tests/test_task_router_jarvis_commands.py`.
2. **Bileşik komutlar** (`_compound_route`): "X'i araştır ve belgele" → sıralı
   çok adımlı plan; muhafazakâr bölme (her parça ≥0.8 güvenle rotalanmalı).
   Zamir devamları ("bunu belgele", "sonucu bana mail at" → `me` alıcı çözümü)
   paralel oturumda eklendi. Testler: `tests/test_compound_dispatch_chain.py`.
3. **Yazıcı araç zinciri** (`capability_registry._writer_source_context`):
   document/spreadsheet/presentation/canvas artık önceki adımın çıktısını
   (özet + kaynaklar) içerik olarak devralıyor.
4. **SwiftUI gözlem düzeltmesi**: ChatView `@ObservedObject var chat` oldu
   (eskiden appState üzerinden computed — mesajlar 25 sn'lik watchdog'a kadar
   ekrana düşmüyordu).
5. **Self-pairing** (`bridge.pairing_self_pair` + `_ensure_self_paired_async`):
   masaüstü, telefonsuz kendi pairing oturumunu kendi user token'ıyla claim
   edip runtime'ı register ediyor. Girişte (`backend.auth_sync_session`) ve
   açılışta (`bootstrap`) otomatik. Canlıda doğrulandı (register 200, ws OK).
6. **Yerel-öncelikli chat** (Swift): `PythonRuntimeSupervisor.sendLocalChat`
   → `ChatStore.localSend` → bulut "masaüstü ortamı yok" retleri bitti.
   Canlı doğrulandı: "safariyi aç" gerçekten Safari'yi açıyor.
7. **Yapılandırılmış planlama** (`structured_planner.py`, `elyan.plan.v1`):
   araç kataloğu (JSON Schema) + kurallar + yanıt şeması tek JSON zarf; plan
   tek noktada doğrulanıyor. Bu oturumda eklenen: öğrenilmiş rota geçmişi
   (`intelligence_context`) ve masaüstü canlı durumu (`context.desktop`)
   zarfa veri olarak giriyor; geçersiz plana tek turluk yapılandırılmış
   onarım (`elyan.plan.repair`); eski 80 satırlık düz metin planner prompt
   silindi. Testler: `tests/test_structured_planner_contract.py`.

Test durumu: `./venv/bin/python -m pytest tests/ --ignore=tests/electron`
→ 423 passed. Swift build: `xcodebuild -project ElyanMac.xcodeproj -scheme
ElyanMac -configuration Debug build` → SUCCEEDED.

## Sıradaki işler (öncelik sırasıyla)

1. ~~**desktop_operator planner'ı yapılandırılmış sözleşmeye taşı**~~ ✅ (2026-07-08)
   Serbest metin operatör prompt'u silindi; yeni `runtime/operator_planner.py`
   (`elyan.operator.v1`) eylem kataloğu + sanitize gözlem + kurallar + yanıt
   şemasını tek JSON zarfı olarak gönderiyor. `plan_visual_operator_steps`
   artık `validate_operator_plan` ile tek noktada doğruluyor + tek turluk
   yapılandırılmış onarım (`build_repair_request`) uyguluyor. Testler:
   `tests/test_operator_planner_contract.py` (11 test). Suite: 434 passed.
2. ~~**Yerel sohbetlerin bulut geçmişine senkronu**~~ ✅ (2026-07-09)
   Keşif: `POST /v1/chat/messages` her zaman sunucu beynini çalıştırıyor
   (assistant cevabını backend üretip client polluyor) — "sadece kaydet" modu
   yok, backend kodu bu repoda değil. Yani bulut'a mirror uygulanabilir değildi.
   Ayrıca kök neden bulundu: `_sync_conversation_truth_from_backend` items'ı
   backend session listesinden yeniden kuruyor, yerel-öncelikli konuşmaları
   (id "conv_...") **her senkronda siliyordu**. Yapıldı:
   (a) sync artık yerel-öncelikli konuşmaları koruyor (`clear_all` hariç);
   (b) yerel→backend promote edilen yer tutucu, senkron öncesi düşürülüyor
   (kopya olmasın); (c) yeni `conversation.detail` capability yerel mesajları
   döndürüyor; (d) Swift `SessionHistoryView` bulut session'larıyla yerel
   konuşmaları (bridge `conversation.list`, UUID olmayan id'ler) birleştiriyor,
   "Yerel" rozeti + yerel detay/silme yolları. Testler:
   `test_backend_truth_sync_preserves_local_only_conversations` +
   `..._clear_all_drops_local_conversations`. Suite: 436 passed. Swift build:
   SUCCEEDED.
3. ~~**Plan onay UX'i**~~ ✅ (2026-07-09)
   Çok adımlı/yan etkili planlar artık ChatView'da adım listesi + Onayla/İptal
   butonlu `PlanCard` olarak çiziliyor (eskiden "onayla" yazmak gerekiyordu).
   Akış: `sendLocalChat` yanıtındaki `planPreview/pendingPlanId/needsConfirmation`
   parse edilip `ChatMessage.plan`'a (`PendingPlan{summary, steps, ...}`)
   bağlanıyor; butonlar `conversation.confirm_plan`'ı çağırıyor
   (`confirmLocalPlan` → ChatStore.confirmPlan). Onayda sonuç yeni baloncuk,
   iptalde iptal mesajı; "onaylanıyor" durumunda butonlar kilitli. Dosyalar:
   ChatStore (PlanStep/PendingPlan modelleri), PythonRuntimeSupervisor
   (parse + confirmLocalPlan), AppState (wiring), ChatView (PlanCard). Swift
   build: SUCCEEDED.
4. **Canlı akış** — yerel yol senkron tek cevap dönüyor; uzun görevlerde adım
   adım ilerleme göstermek için bridge'in unsolicited event'leriyle
   (onUnsolicitedResponse) streaming benzeri güncelleme yapılabilir.
5. **Eval setini büyütme** — kullanıcının gerçek ıskalayan komutları
   `test_task_router_jarvis_commands.py`'a eklenerek döngü kapatılmalı.
6. **ReAct döngüsü** — executor statik planı koşuyor; adım sonucunu planlayıcıya
   geri besleyip devam/revize kararı aldırmak (yapı: executor_core +
   structured_planner repair zarfının genellenmesi).

## Cowork / tool / skill geliştirme (2026-07-09, sürüyor)

Kullanıcı isteği: cowork, tool kullanımı ve skill katmanını çok daha geliştirmek.
- ✅ **Skill kütüphanesi büyütüldü** (`skill_catalog.BUILTIN_SKILL_DEFINITIONS`):
  5 yeni bileşik skill — `research.present` (web_research→presentation_write),
  `research.report` (web_research→document_write), `data.analyze_and_chart`
  (data_analyze→chart_generate), `screen.explain` (observe_screen),
  `image.describe` (image_read). Hepsi tetik cümlelerini net farkla rank ediyor
  (alias map: arastir→research, sunum→presentation, grafik→chart vb). Testler:
  `test_skill_runtime_catalog.py` + `test_skill_runtime_selection.py`. 438 passed.
- ✅ **ReAct adım geri beslemesi** (`executor_core.execute_plan_steps`): statik
  plan iptali yerine, adım araç/doğrulama hatasıyla düşünce opsiyonel `replan_fn`
  kalan planı revize edebiliyor (indeks tabanlı splice döngü, `max_replans=2`
  bütçe, geriye uyumlu — fn yoksa eski davranış). Bağlam: failedCapability,
  errorCode, failedArgs, remainingSteps. Bridge'de deterministik `_recoverable_replan`:
  web_research ağ hatası → yerel `retrieve_context` fallback, kalan yazıcı adımı
  (outputPath dahil) korunur. Testler: `test_executor_core_contract.py` (3 ReAct)
  + `test_runtime_bridge_contract.py` (2 replan). 443 passed.
- ✅ **Cowork doğrulama + izleme**: (a) ReAct `_recoverable_replan` cowork
  remote-task executor yoluna da bağlandı; (b) `state_store.record_capability_execution`
  gerçek yürütme başarısını/başarısızlığını `capabilityQuality`'ye yazıyor
  (routing sonuçlarından ayrı); (c) bridge `_execute_step_with_telemetry` her
  adımı kaydediyor (iki executor yolu da); (d) `structured_planner.intelligence_context`
  sık başarısız (≥3 yürütme, ≥%34 hata) araçları planlayıcıya "reliability"
  kaydı olarak bildiriyor. Testler: 3 yeni. 446 passed.
- ✅ **Yeni capability: pano (clipboard)**: `actions/clipboard.py` (pbpaste/pbcopy)
  + `clipboard_read` (read_only) ve `clipboard_write` capability'leri
  (capability_registry: decl/adapter/handler/metadata/darwin-only;
  safety_policy KNOWN_SAFE_TOOLS). Deterministik router: "panoda ne var/panodakini
  oku" → read, "X'i panoya kopyala/panoya kopyala: X" → write (dosya-kopyalama
  rotasından önce; cp regresyonu yok). Testler: router (3) + capability (1). 450 passed.

Tüm cowork/tool/skill geliştirme eksenleri (skill, ReAct, cowork izleme, yeni tool)
tamamlandı.

## Jarvis hız + isabet turu (2026-07-09)

Hedef: uygulamadan verilen komut anında, yerel, gerçek yürütülsün.
- ✅ **Ağ round-trip'i atlandı** (`send_conversation`): deterministik router
  ≥0.8 güvenle eşleşiyorsa paylaşılan-beyin bağlamı için backend'e HİÇ gidilmiyor
  (brain_profile + retrieval_search çağrıları yerel komutu ~600ms geciktiriyordu).
- ✅ **State cache** (`state_store`): mtime-doğrulamalı in-process cache; komut
  başına ~19 load_state'in dosya-oku+parse+_ensure_defaults maliyeti kalktı.
  Dış yazımda otomatik geçersizleşir (tek-yazıcı varsayımına güvenmez).
- ✅ **Kompakt JSON** kayıt (indent yok) — encode + disk yükünü azalttı.
- **Ölçüm**: yerel komut ~1000ms → **~280ms** (3.5x). 450 test geçiyor.
- ✅ **Router isabeti**: `_sys_info_query` artık ekli/çekimli Türkçe biçimleri
  kök-önekle yakalıyor ("pilim", "şarjım", "diskte", "işlemci yükü") — eskiden
  tam-token eşleşme "pilim"i ıskalıyordu. Yanlış-pozitif koruması ("bu işlemi
  yap" → CPU değil). Testler: test_task_router_jarvis_commands.py.

Swift build: SUCCEEDED. Değişiklikler commit'lenmedi (branch v2-desktop-design).
Not: LLM planlaması gereken serbest komutlar hâlâ giriş+sunucu beynine bağlı
(yerel LLM bilinçli olarak yok); deterministik komut ailesi tamamen offline+hızlı.

## Backend bağlantısı + kota senkronu (2026-07-09)

Mobil→sunucu→desktop cowork dispatch akışı zaten tam kurulu (WS `task.dispatch`
→ack→execute thread + polling fallback + task.update/artifacts geri raporlama;
register/heartbeat/self-pairing). Kapatılan boşluk: **kota/usage senkronu**.
- ✅ `_refresh_billing_truth_async` (throttle 15s, arka plan): backend'den taze
  abonelik+usage çeker (auth_me → _apply_subscription_truth). Dispatch görevi
  terminal olunca (`_report_runtime_task_terminal_result` — hem WS hem polling
  yolu buradan geçer) ve server_brain sohbeti sonrası tetikleniyor. Desktop
  kotası kredi tükendikçe sunucuyla senkron kalıyor.
- Swift BillingView zaten sunucudan taze çekiyor; state senkronu tamamlıyor
  (mobil/desktop/server üçlüsü tutarlı). Testler: 2 yeni, 454 passed.

## Operatör isabeti (PC kontrolü) derinleştirildi (2026-07-09)

Yeni yetenek yok; mevcut `desktop_operator` hedef-seçim isabeti (observe→**locate**
→execute→verify döngüsünün darboğazı) üst seviyeye çıkarıldı:
- ✅ **Fuzzy/typo toleransı** (`_rank_targets` + `difflib`): "safar"→Safari,
  "sittings"→Settings. Yüksek eşik (0.72/0.8/0.9 tier), kesin-hit'lerin altında
  puan → yanlış hedef seçmez, yakın-tie reddi korunur.
- ✅ **Çift yönlü TR↔EN UI eşanlam** (`_REVERSE_UI_SYNONYMS`, tek kaynaktan
  türetilir): İngilizce sorgu Türkçe butonu bulur ("send"→Gönder) ve tersi.
- ✅ **Eşanlam sözlüğü genişletildi** (~50 fiil/isim: aç/open, yenile/refresh,
  indir/download, paylaş/share, seç/select, onayla/confirm ...).
Helper Swift (swiftc; Quartz/CGEvent C API'lerini çağırır) — transport'a
dokunulmadı. Testler: 4 yeni, 458 passed.

## Görsel indir + kaydet otonom tamamlandı (2026-07-09)

"kedi resmi bul VE masaüstüne kaydet" komutunun "kaydet" kısmı artık gerçekten
çalışıyor — kırılgan pikselli GUI yerine %100 güvenilir doğrudan HTTP indirme.
- ✅ **Yeni yetenek `image_fetch`** (`actions/image_fetch.py`): bir konu için
  Openverse API'den (yedek: Wikimedia Commons) DOĞRUDAN görsel indirir ve
  kullanıcının klasörüne yazar. Öne çıkanlar: tam URL başarısızsa Openverse
  thumbnail proxy'sine düşer; content-type + magic-byte ile uzantı tespiti;
  çakışma-güvenli dosya adı (`-2`, `-3`); 25 MB indirme sınırı; hedef klasör
  **yalnız ev dizini altına** kısıtlı (varsayılan `~/Desktop`).
- ✅ **Kayıt** `capability_registry` (tool decl + adapter + `requests` bağımlılığı
  + kategori/verification/timeout/grup + handler lambda) ve `safety_policy`
  `KNOWN_SAFE_TOOLS` (onay sürtünmesi yok — komuttaki "kaydet" niyet açık).
- ✅ **Router** (`task_router._image_find_route`): "kaydet/indir" niyeti varsa
  `image_fetch`'e (masaüstü/indirilenler/resimler/belgeler hedef çıkarımı ile)
  gider; yoksa eskisi gibi tarayıcı görsel araması. Ayrıca `_sys_info_query`
  ağ tespiti düzeltildi — "internetten" (ablatif kaynak) artık yanlışlıkla
  "network" durum sorgusu sanılmıyor.
- Deterministik yol tek turda çalışır (requires_confirmation/multi_step=False →
  doğrudan `run_capability`). Testler: 10 yeni (`tests/test_image_fetch.py` +
  router save-route testi), suite **476 passed**. Saf Python — Swift rebuild
  gerekmez, app relaunch (bridge yeniden başlar) yeterli.

## Kod-ajanı v1: okuma-tarafı desktop tool registry (2026-07-09)

Hedef: Elyan'ı Claude Code benzeri masaüstü coworker'a taşımak. Bu tur, tam
yol haritasının **1. dilimi** — kod-ajanı döngüsünün ("repo'yu anla → ilgili
dosyaları bul") temeli olan READ-ONLY dev tool seti. Hepsi güvenli (yazma yok),
izin kapısı gerektirmez (permission modeli: read_only tier), tam test kapsamlı.
- ✅ **`actions/filesystem.py`**: `file_read` (satır aralığı + binary reddi +
  gizli-yol denylist: id_rsa/.ssh/.aws/keychain), `file_search` (ripgrep varsa
  onu, yoksa saf Python; node_modules/.git/venv... atlar), `directory_tree`
  (gürültü klasörlerini atlar, derinlik/giriş sınırı).
- ✅ **`actions/git_ops.py`**: `git_status` (branch + staged/unstaged/untracked
  yapılandırılmış), `git_diff` (worktree/--staged, büyük çıktı kısaltılır).
  Yalnız okuma alt-komutları; mutasyon (commit/push) YOK.
- ✅ **Kayıt**: `capability_registry` (5 tool decl + adapter + handler + yeni
  **"developer" (Geliştirme / Kod)** capability grubu + kategori/verification/
  timeout), `safety_policy.KNOWN_SAFE_TOOLS` (5'i de). Metadata: category=
  developer, permClass=read_only, verify=result_nonempty, cross-platform.
- ✅ **Router** (`_developer_tool_route`, SHELL rotasından ÖNCE): "git durumu/
  diff", "proje yapısı/klasör ağacı", "kodda/projede X ara" → dev tool'lar.
  Guard: git log/commit/push gibi diğer git komutları ham shell'e kalır;
  file_read NL rotası bilinçli EKLENMEDİ (document_read çakışması) — o ajan-içi
  capability olarak dururyor. Testler: 17 yeni (filesystem 10 + git 5 + router
  2). Suite **493 passed**. Saf Python — Swift rebuild yok, relaunch yeter.

## Kod-ajanı v1: yazma-tarafı desktop tool registry (2026-07-09)

Yol haritasının **2. dilimi** — kod-ajanı döngüsünün "patch uygula → commit"
kısmı. Hepsi mutasyon → izin kapısından geçer (onaysız ÇALIŞMAZ; executor
onaylı planlarda `_confirmed=True` enjekte eder → PlanCard onayı otomatik).
- ✅ **`actions/file_write.py`**: `file_write` (oluştur/overwrite; gizli-yol
  denylist; açık-yol veya cwd-altı kısıtı), `file_patch` (çıpalı bul/değiştir:
  old_string→new_string, benzersizlik guard'ı + replace_all; unified diff
  önizleme). Sözleşme bilinçli olarak Claude Code Edit modeli (LLM'in güvenilir
  ürettiği biçim), unified-diff parse değil.
- ✅ **`actions/git_ops.py` (mutasyon)**: `git_commit` (opsiyonel `git add -A`;
  **PUSH YAPMAZ**; nothing-to-commit guard), `git_branch` (oluştur+checkout;
  boşluklu ad reddi). `_current_branch` helper doğmamış/detached HEAD'i düzgün
  okur.
- ✅ **İzin kapısı**: `safety_policy.WRITE_CAPABILITIES` (file_write/file_patch)
  + yeni `GIT_MUTATION_CAPABILITIES` git_guard (git_commit/git_branch) — ikisi
  de `_confirmed` şart, hiçbiri KNOWN_SAFE değil, fail-safe (onaysız → yazmaz).
- ✅ **Kayıt**: capability_registry (4 tool decl + adapter + handler + developer
  grubu + _SIDE_EFFECT + _NON_RETRYABLE(patch/commit/branch) + verification:
  file_write/patch=artifact_exists, git=result_nonempty). **Router**: "commit
  yap / 'mesaj' commit'le" → git_commit, "yeni branch X oluştur" → git_branch,
  ikisi de `requires_confirmation=True`. `_extract_quoted_message` Türkçe
  ek-kesme işaretini (commit'le) mesaj sanmaz. Guard: git log/push shell'e kalır.
- Canlı test (throwaway repo): write→patch→branch→commit zinciri çalıştı;
  onaysız file_write BLOKLANDI + dosya oluşmadı. Testler: 21 yeni (file_write 11
  + git commit/branch 5 + safety gate 4 + router 1 güncelleme). Suite **514
  passed**. Saf Python — relaunch yeter.

### Kalan yol haritası (öncelik sırasıyla — kullanıcı spec'i)
Bu diliminden sonra sıradaki dilimler (henüz YAPILMADI):
1. **`git_push` + `pr_create`** (external_action tier — remote'a dokunur, ekstra
   onay + `allow_destructive`/network guard). Yerel commit/branch bitti; kalan
   remote adımı bilinçli ertelendi.
2. **`test_run` / `error_parser`**: npm/pnpm/pytest/go test algıla + çıktıyı
   dosya:satır'a bağla (shell_run üstüne yapılandırılmış sarmalayıcı).
3. **`repo_map` / `code.read_symbol`**: framework/pkg-manager/entrypoint/test
   sistemi çıkarımı + sembol-bazlı arama (mevcut file_search + dil-farkında pass).
4. **Verification layer'ı zorunlu kıl**: her görev "şu kanıtla tamamlandı"
   (test geçti / build geçti / diff gösterildi / checksum) döndürsün — capability
   metadata'daki `verificationMode` bunun iskeleti; executor'da enforce et.
5. **Task state machine + arka plan job'ları** (backend, bu repoda değil):
   tasks/task_steps/tool_runs/approvals/artifacts/verification_results tabloları;
   `waiting_for_device` durumu (desktop offline). Mobil = task console.
6. **MCP connectors**: GitHub/Gmail/Drive/Notion/Calendar/Supabase/Linear —
   `mcp_runtime` + `mcp_call_tool` altyapısı mevcut; connector kayıtları eklenir.
7. **`ELYAN.md` proje bağlamı** (CLAUDE.md muadili): repo kuralları/komutları/
   forbidden actions; retrieval ile yalnız ilgili parçalar prompt'a girsin.
8. **Subagent routing**: planner/coder/reviewer/tester/research/operator/security
   rolleri — ayrı servis değil, orchestrator içinde role-based execution.

## "Yanıt alınamadı" reliability düzeltmesi (2026-07-09)

Kök neden: `sendLocalChat` guard'ı `isRunning && runtimeReady` istiyordu.
`runtimeReady` bir BACKEND/bootstrap bayrağı (satır 657-742). Backend yavaş/
kapalıyken, backend'e ihtiyaç DUYMAYAN yerel deterministik komut (git durumu,
dosya, saat) bile reddediliyor → `send()` bunu yakalayıp KÖR buluta düşüyor →
bulut SSE boş kapanıyor → ChatStore `streamDidClose()` "Yanıt alınamadı." basıyor.
Doğrulandı: `RuntimeBridge().handle(conversation.send, 'git durumu')` backend
olmadan doğru cevabı veriyor — yani süreç canlıyken yerel komut çalışır.
- ✅ **`sendLocalChat` guard'ı `isRunning`'e gevşetildi** (yerel komut backend'e
  bağlı değil). PythonRuntimeSupervisor.swift.
- ✅ **`ensureLocalReady()`** eklendi: bridge düşükse crash-restart ile yarışmadan
  (çift-bridge token yarışını önler) süreci toparlar, ~8s canlılık bekler.
- ✅ **`send()` bridge-down yolu**: kör buluta düşmeden önce `localRecover()` +
  yerel bir kez daha dener; ancak o da olmazsa buluta düşer. (ChatStore + AppState).
- ✅ **Çıplak "Yanıt alınamadı."** → eyleme dönük mesaj ("motor yeniden bağlanıyor
  olabilir, tekrar dene"). Swift build: **SUCCEEDED**.
- Test: app'i Cmd+Q ile kapat, yeniden aç; `git durumu` yaz — artık backend
  yavaş olsa da yerelde cevaplanır, "Yanıt alınamadı" yok.

## SAF DETERMİNİSTİK MOD — dış LLM/bulut bağımlılığı kaldırıldı (2026-07-09)

Kullanıcı isteği: "yanıt gelmedi" bitene kadar LLM/bulut yolunu komple kaldır,
saf deterministik otomasyon. Yapıldı:
- ✅ **Swift `send()` saf-yerel**: `ensureRealtimeOpen()` (bulut SSE) + `backend.
  sendChatMessage` dispatch KALDIRILDI. Akış: `localRecover()` (bridge düşükse
  toparla) → `localSend`. Başarısızsa GERÇEK durum gösterilir (`localStatus` =
  lifecycleState+lastError). Boş-bulut "yanıt gelmedi" sınıfı artık imkânsız.
  `finishLocal()` helper baloncuğu net metinle doldurur.
- ✅ **Python `conversation.send` deterministik-only**: `ELYAN_DETERMINISTIC_ONLY=1`
  (RuntimeBridgeSwift env'e enjekte ediyor). `_route_chat` eşleşmeyen komutta
  `_semantic_route` (backend/LLM) yerine `_deterministic_fallback_reply` (yerel
  yardım) döndürür. `skip_shared_context` de zorlanır → **sıfır backend çağrısı**.
  Testler env'i set etmediği için semantic yol testte korunur (**514+4 passed**).
- Doğrulama: det. modda 'git durumu'/'proje yapısı' çalışıyor, 'fıkra anlat' →
  yardım, hiç `brain_retrieval_search` yok. Swift build SUCCEEDED.
- **Geri almak için**: RuntimeBridgeSwift.swift'te `ELYAN_DETERMINISTIC_ONLY`
  satırını sil (ya da "0" yap) → semantic/bulut yolu geri gelir.

## Canlı checklist akışı + doğrulama-kapılı ilerleme (2026-07-09)

Çok-adımlı plan yürütülürken adımlar canlı checklist olarak akıyor; her adım
diske/araca göre doğrulanmadan sonrakine geçilmiyor.
- ✅ **Doğrulama-kapılı ilerleme ZATEN vardı**: `execute_plan_steps` her adımı
  `verificationMode` ile doğrular (`_verify_step_result`), geçmezse retry→replan
  (`_replan_remaining`, max 2), geçemezse durur. (Kanıt: artifact üretmeyen
  document_write adımı `failed` işaretlendi.)
- ✅ **Canlı checklist emit (yeni)**: `ExecutorCore.set_progress_emitter` +
  `_emit_progress` — her adım geçişinde (`_record_step_started/_result`,
  `finish_execution`) bir **task_trace bloğu** üretir (steps[]: pending/running/
  completed/failed, capability→TR label). Bridge `main()` içinde `emit_progress`
  ile stdout'a `conversation.progress` unsolicited event olarak akıtır.
- ✅ **Swift consume**: `PythonRuntimeSupervisor.onProgress` → AppState →
  `ChatStore.applyProgressBlock` aktif mesaja task_trace bloğunu upsert eder
  (progressHostId; executor cid taşımadığı için hedef bu). `confirmPlan` onayda
  CANLI baloncuk açar, checklist orada tik atar, sonuç aynı baloncuğa (block-first
  render nedeniyle final metin text-block olarak) yerleşir.
- ✅ **`TaskTraceBlockView` yükseltildi**: eskiden sadece "düşünme dalgası"
  çiziyordu; artık adımları durum ikonlu checklist (çalışanda spinner) çizer.
- Testler: 3 yeni (`test_executor_progress_stream.py`). Suite **521 passed**.
  Swift build SUCCEEDED. Python değişti → relaunch; Swift değişti → zaten rebuild edildi.

## "araştır+belge" planı + takılı checklist düzeltmesi (2026-07-09)

Belirti (ekran görüntüsü): "dif geo ... aratır ve 4 sayfa belge oluştur" tek
`document_write`'a düşüyordu (gerçek araştırma yok, dosya adı = istek); checklist
"Belge yazılıyor" spinner'ında takılı kalıyordu.
- ✅ **Araştırma fiili tespiti düzeltildi**: `_RESEARCH_STEM_RE = aras?tir`
  → hem araştır hem **aratır**'ı yakalar (kullanıcı "aratır" yazmıştı). Böylece
  compound tetikleniyor: `[web_research → document_write]`. (öğren/derle/analiz
  bilinçli DIŞARIDA — web-arama/veri-analiziyle çakışıyordu; test bunu yakaladı.)
- ✅ **Profesyonel veri akışı**: `_compound_route` artık araştırma konusunu +
  sayfa hedefini (`_extract_page_count`) yazıcı adımının prompt/title'ına enjekte
  eder; `_strip_research_verbs` ile sorgu temizlenir ("yapay zeka öğren"→"yapay
  zeka"). Yürütücü web_research çıktısını `_previousResult`→`_writer_source_context`
  ile document_write'a geçirir → belge GERÇEK araştırmayla dolar (zaten vardı).
- ✅ **Takılı checklist kökten çözüldü**: `ChatStore.finalizeChecklist` — plan
  çözülünce (confirmPlan başarı/hata) kalan running/pending adımları deterministik
  kapatır, overall status'u set eder. Final progress event'i yarışta kaybolsa bile
  spinner ASLA takılı kalmaz.
- Uçtan uca doğrulandı (bridge, det. mod): send→plan[web_research,document_write]
  →confirm→"Web araştırması tamamlandı"+"DOCX oluşturuldu", progress overall
  **completed**. Suite **521 passed**, Swift build SUCCEEDED.

## Çapraz platform turu (2026-07-09) — Windows + Linux

Kullanıcı spec'i: macOS'ta Swift, Windows/Linux'ta Flutter; Python (+C helper)
motoru HER platformda aynı; arayüz %100 birebir; tek beyin VPS server_brain
(yerel LLM yok — bu zaten böyle, `env.removeValue(ELYAN_DETERMINISTIC_ONLY)`);
mobil→görev→yürütme akışı sorunsuz.

### Yapılan 1: Motor çapraz platform (commit `feat(runtime): open_app/...`)
- `clipboard.py`: platform seçimli (pbpaste/pbcopy · PowerShell Get/Set-Clipboard
  · wl-clipboard→xclip→xsel). `open_app.py`: Windows `cmd /c start` + hedef
  eşleme (`_WINDOWS_LAUNCH_TARGETS`), Linux aday listesi (`_LINUX_LAUNCH_TARGETS`)
  + gtk-launch yedeği. `close_app`: psutil terminate→kill (tüm platformlar).
- 4 yetenek `_DARWIN_ONLY_CAPABILITIES`'ten çıktı. Kalan darwin-only: takvim/
  anımsatıcı/WhatsApp/ekran-analizi/desktop_operator (helper Swift'e bağlı).
- shell/state_store/app_config zaten platform-farkındaydı (powershell/bash,
  APPDATA/XDG). Testler: `tests/test_cross_platform_desktop.py`. **529 passed**.

### Yapılan 2: Flutter desktop iskeleti (`apps/desktop/` — elyan_desktop)
Windows/Linux arayüzü; macOS target'ı YALNIZ geliştirme doğrulaması için
(sandbox kapatıldı — bridge alt süreci için gerekli; macOS'a Swift app çıkar).
- **Tema** (`lib/theme/elyan_theme.dart`): SwiftUI ElyanTheme renkleri birebir
  (canvas F2EEE5/1B1B19, userBubble E5DFD3/2E2E2B, composer FBF9F4/252523,
  surface F8F5EF/282826, hairline %8) — test dosyası bu eşitliği assert ediyor.
- **Köprü** (`lib/bridge/runtime_bridge.dart`): RuntimeBridgeSwift portu —
  aynı JSON-lines sözleşmesi, repo-kökü çözümü (ELYAN_REPO_ROOT→cwd→exe'den
  yukarı), venv python (win: venv\Scripts\python.exe) → paketli runtime
  (`build/runtime/<os>/elyan-runtime`) önceliği, unsolicited event'ler,
  çökme algılama.
- **Supervisor** (`lib/bridge/runtime_supervisor.dart`): bootstrap, auth senkronu
  (`backend.auth_sync_session` aynı payload), sendLocalChat/confirmLocalPlan
  (`conversation.send/confirm_plan`), `conversation.progress` → onProgress,
  crash-restart (tek zamanlayıcı, çift-bridge yarışına dikkat).
- **Store/UI**: ChatStore (iyimser baloncuk, saf-yerel send, canlı checklist
  upsert + finalizeChecklist), ChatView (balonsuz asistan, krem kullanıcı
  balonu r18, hap composer r22, Düşünüyor…, PlanCard, PermissionCard,
  TaskTrace checklist), AppShell (sidebar+profil çipi), LoginView
  (email/şifre + kayıt; `/v1/auth/*` mobil ile aynı gövde). `flutter analyze`
  temiz, 3 Dart testi geçiyor.

### Kalan işler (Flutter parite — öncelik sırasıyla)
1. **Blok render tamlığı**: şimdilik text + task_trace tam; ChatBlock.swift'teki
   ~30 blok türü (code, table, chart, file, web_search, markdown...) generic'e
   düşüyor. Markdown renderer ekle (markdown paketi), sonra blok blok port et.
2. **Görünümler**: ~~TaskInboxView~~ ✅ (onay diyaloğu + rozet + backend.tasks.
   approval/execute_assigned bağlı), Pairing = durum kartı ✅ (tam QR akışı
   kaldı). Kalan: SettingsView/Profile, BillingView, SessionHistory bulut
   oturumları (backend getSessionsPage) — şu an yalnız yerel `conversation.list`.
3. **Google OAuth** (LoginView.swift'teki akış) + avatar çekme.
4. **Paketleme**: `build/runtime/windows|linux/elyan-runtime` PyInstaller
   hedefleri (pyinstaller/ klasöründe macOS spec'i var — çoğalt), Flutter
   installer (msix / AppImage-deb).
5. **Windows/Linux'ta gerçek doğrulama**: bu makine macOS; Windows/Linux VM'de
   uçtan uca (login→pairing→mobil görev→yürütme) test edilmeli.
6. Ekran operatörü (desktop_operator) Windows/Linux muadili — uzak dilim
   (helper mimarisi: pywinauto/AT-SPI adayları).

## DMG öncesi güvenilirlik turu (2026-07-09, akşam)

Kullanıcı raporu: "sunum hazırlanıyor" spinner'ı saatlerce takılı görünüyordu.
Üç kök neden bulunup düzeltildi (commit: `fix(macos+runtime): takılı ...`):
1. **ChatMessage == blocks.count vekili** yerinde blok güncellemesini (canlı
   checklist tikleri, finalize) görmüyordu → `revision` sayacı eklendi; her
   yerinde blok mutasyonu artırmalı (applyProgressBlock/finalizeChecklist/
   completeStreaming/finishLocal yapıyor). YENİ yerinde blok mutasyonu
   eklerken revision'ı artırmayı unutma.
2. **Block-first render tuzağı**: mesajda blok varken `.text` çizilmez —
   final metin text BLOĞU olarak eklenmeli (confirmPlan zaten yapıyordu;
   completeStreaming/finishLocal'a da eklendi).
3. **"araştırıp" (-ıp ulacı)** compound tetiklemiyordu; `_RESEARCH_CONVERB_RE`
   ile bölünüyor. Yazıcı dosya adı araştırma konusundan türüyor.
   `presentation_write._derive_slide_specs`: "N sayfalık" → N slayt (bulgular
   dağıtılır + Kaynaklar kapanışı). Suite 536 passed.

## Bilinmesi gerekenler

- Backend: `https://api.elyan.dev` (config/api_keys.json). Runtime durumu:
  `~/Library/Application Support/Elyan/state/elyan_state.json`.
- **İki bridge sürecini aynı anda çalıştırma** — refresh token rotasyonu
  yarışıp oturumu düşürüyor (test sırasında bir kez yaşandı).
- Yerel modeller bilinçli olarak kapsam dışı bırakıldı (kullanıcı istemedi).
- Değişiklikler commit'lenmedi; working tree'de duruyor (branch:
  v2-desktop-design).
