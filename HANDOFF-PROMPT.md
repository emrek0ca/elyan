# Elyan — Oturum Devir Prompt'u (başka bir Claude Code oturumuna ver)

Sen Elyan projesinde çalışan kıdemli bir mühendissin. Kullanıcı Türkçe konuşur,
kod yorumları Türkçedir; Türkçe yanıt ver. Testler yeşil olmadan yayın yapma.

## Mimari (özet)

Elyan = telefondan gönderilen görevleri kullanıcının bilgisayarında yürüten
masaüstü ajanı. Üç repo, hepsi `~/Desktop/` altında:

- **`~/Desktop/elyan`** — Masaüstü runtime (Python) + CLI + npm paketi (`elyan`).
  GUI yok: daemon + pystray tepsi ikonu. Branch: `v2-desktop-design`.
  Beyin = VPS'teki server_brain (api.elyan.dev). Testler: `venv/bin/python3 -m pytest tests/ -q`.
- **`~/Desktop/elyan-backend`** — Fastify+Postgres (api.elyan.dev). Branch `v2-blocks`.
  Deploy: `bash scripts/deploy-v1-release.sh` (yalnız kullanıcı isterse).
- **`~/Desktop/mobile-elyan`** — Flutter iOS uygulaması. Test: `flutter test`.

## Bu oturumda yapılanlar (hepsi commit'li)

### elyan (runtime) — "mini-Codex" turu
1. **Routing**: "Chrome'dan kedi resmi aç" gibi uygulama+içerik cümleleri artık
   `open_app`'e uydurma ad göndermiyor — tarayıcıysa `open_app + browser_control`
   planı, değilse LLM planlayıcıya delegasyon (`task_router._split_app_content_target`,
   `_route_app_content_open`, bridge `_remote_task_should_delegate_to_llm`).
   YouTube/Gmail/Netflix gibi web servisleri `_WEB_SERVICE_URLS` ile tarayıcıda açılıyor.
2. **Hata taksonomisi**: "uygulama bulunamadı" = `APP_NOT_FOUND` (CAPABILITY_UNAVAILABLE
   değil); replan gözlemine kurulu-uygulama önerileri (`suggest_installed_apps`);
   `_recoverable_replan` bozuk open_app hedefini yerinde düzeltiyor; "3 kanıt eksik"
   yerine insanca mesajlar; görev düşünce gerçek hata mesajı korunuyor.
3. **Görev yaşam döngüsü**: daemon başlarken hayalet 'running/unknown' görevleri
   süpürüp backend'e failed raporluyor (`sweep_interrupted_tasks`); görev
   güncellemeleri başlık taşıyor (tepsi + `elyan tasks` anlamlı).
4. **WS "ABNF"**: websocket-client sunucu close frame'ini on_error'a ham ABNF nesnesi
   geçiriyormuş; artık kapanış kodu/nedeni loglanıyor (`ws_server_close`), backend'in
   `4001 replaced` kapanışında 3 sn bekleyip yeniden bağlanıyor (kapışma kırıldı).
5. **Faz 1 — `actions/browser_session.py`**: kalıcı Playwright oturumu (tek işçi
   thread + komut kuyruğu). Yetenekler: `browser_session.goto/click/type/extract/
   snapshot/download/close`. Oturum: önce çalışan Chrome CDP (9222/9223), yoksa
   Elyan kalıcı Chrome profili `~/.elyan/browser/profile` (kullanıcı sitelere BİR KEZ
   giriş yapar, kalıcı). İndirme `outputPath` artifact'ı döndürür. Şifre alanına
   yazma engelli. + `make_directory`, `file_move` (actions/file_write.py).
6. **Faz 2 — executor değişkenler + forEach** (`executor_core.py`): adım çıktıları
   `step_outputs`'ta; args'ta `{{steps.<id>.result.items[0].href}}` şablonları
   (tam-şablon tip korur); `forEach: "{{steps.x.result.items}}"` fan-out
   (`{{item...}}`, `{{index}}`, sınır 20). Çözülmeyen referans `TEMPLATE_UNRESOLVED`.
   Plan şemasına `forEach` alanı + planner kurallarına dataFlow/fanOut/browserWork
   rehberi eklendi (structured_planner.py).
7. **Faz 3 — ReAct ajanı** (`runtime/browser_agent.py`): `browser_agent.run(goal)`
   gözlem→LLM karar→eylem kapalı devresi (elyan.browser_react.v1). Karar verici
   bridge'te `_browser_agent_decide` (sağlayıcı zinciri: server_brain→yerel model).
   Korumalar: tur bütçesi, REACT_STUCK (aynı eylem tekrarı), dürüst REACT_GOAL_FAILED.
   Kayıt: capability_registry (+tool_decl, katalogda), safety_policy
   (allow_browser_control kapısı), uzun görev timeout'u 1200 sn
   (`_execution_timeout_for`, browser_agent/browser_session/desktop_operator).
8. **Diğer**: extras kurulum marker'ı venv içine taşındı (venv yeniden kurulunca
   playwright vb. eksik kalmıyordu → `scripts/install_extras.py`); npm paketi
   `__pycache__`/pyc hariç (package.json files negation); sürüm **1.5.0** bump'landı.
9. **SIGTERM düzeltmesi** (ayrı arka plan oturumundan): `runtime/daemon.py`
   signal.set_wakeup_fd köprüsü — pystray run loop'u sinyalleri ertelese de daemon ölür.

Masaüstü testleri: **637/637 yeşil**. Daemon repo kodundan çalışıyor
(LaunchAgent `dev.elyan.daemon`, cwd=~/Desktop/elyan, venv=~/.elyan/venv) ve
tüm değişikliklerle yeniden başlatıldı (playwright ~/.elyan/venv'e kuruldu).

### mobile-elyan — Codex tarzı tek yüzey (chat-first)
- `conversationViewMode` varsayılanı `sessionOnly` (chat kabuğu); görev gönderince
  görünüm ASLA değişmiyor.
- `/task/:taskId` ayrı görev-detay EKRANI kaldırıldı → chat yüzeyine redirect
  (`/task?taskId=...`); derin bağlantılar (push, QR) kırılmadı; MainTaskScreen
  `initialTaskId` ile görevi chat oturumunda açıyor (`openTaskFromHistory`).
- Inbox sheet görevleri chat oturumunda açıyor (taskThread yalnız oturumu olmayan
  eski görevlere yedek).
- `_resolveActiveTaskId`: chat kabuğunda aktif görev seçimi görünür oturumu izliyor
  (görev izleme/Dynamic Island/onaylar chat'te çalışır).
- Composer'da zaten var: + menü (ekler/kamera/hedef), goal modu
  (`_activateComposerGoalMode`), plan modu, masaüstü dispatch, tam yetki.
- Flutter analyze temiz, **584/584 test yeşil**. Commit'lendi (branch main).

## Tek Spec, Üç Katman mimarisi (bu turda kuruldu)

- `runtime/capability_spec.py` = TEK doğruluk kaynağı: yeni yetenek eklemek
  tek spec bloğu; katalog/handler/güvenlik/doğrulama otomatik türer
  (sözleşme: tests/test_capability_spec_contract.py).
- Skill = görev tarifi: manifest'te id/forEach/{{steps...}} şablonları
  executor'a kadar korunur; ilk tarif `web.collect_download`
  (runtime/skill_catalog.py). Skill yetenek listesi spec'ten türer.
- MCP kanalı: `elyan mcp list|add|remove|enable|disable|tools`; sunucular
  state.skills.mcpServers'ta; MCP sonuçları kanıt sözleşmesine bağlı
  (mcpToolExecuted → stateReadback).
- Öğrenme döngüsü: `elyan tasks --report` başarısız görevleri hata sınıfına
  göre toplar + yatırım rehberi (spec mi / skill mi / MCP mi).

### Kalan spec göçü (68 yetenek) — SONRAKI OTURUM İÇİN OYUN PLANI
Gruplar halinde taşı; her grupta: spec bloğu yaz → legacy decl/adapter/
handler/display kayıtlarını sök → 654+ test paritesini koru. DİKKAT:
- retryable/timeout hâlâ legacy kümelerden (_NON_RETRYABLE_SIDE_EFFECTS,
  timeout if-zinciri) — spec'e alan ekleyip metadata'da migrated yoluna bağla.
- requiredPermissions/permission_class legacy isim kümelerinden geliyor;
  spec.policy'den türet.
- Yazıcılar (document_write vb.) handler'da özel _writer_source_context
  kullanır — build_handler'a custom hook gerekmedikçe en sona bırak.
- Decl metinlerini AYNEN kopyala (planlayıcı davranışı değişmesin).

## ⚠️ Kalanlar / sıradaki işler (öncelik sırası)

1. **npm publish 1.6.0** (sürüm bump'landı; tüm mimari turları içerir) — kod hazır, `npm pack` temiz (1.0 MB / 94 dosya).
   Kullanıcı kendisi yayınlamalı (2FA): `npm login` → `npm publish --otp=<kod>`
   → `npm install -g elyan@1.5.0 && elyan restart`. Kimlik bilgisi/OTP'yi
   Claude'a verme; kullanıcı terminalde kendi girer.
2. **Uçtan uca canlı test**: telefondan (a) "YouTube aç", (b) "Chrome'dan kedi
   resmi aç", (c) serbest hedef: "tarayıcıdan YouTube kanalıma girip son 5
   videomun linkini topla" → browser_agent.run yolu. İlk çalıştırmada Elyan
   Chrome profili açılır; kullanıcı YouTube'a giriş yapmalı.
3. **Backend planner farkındalığı**: server_brain plan üretirken elyan.plan.v1
   zarfındaki yeni kuralları (dataFlow/fanOut/browserWork) ve katalogdaki
   browser_agent/browser_session'ı görüyor (zarf runtime'dan gidiyor) — ama
   backend tarafında prompt/şema sertleştirmesi gerekirse `~/Desktop/elyan-backend`
   brain modülüne bakılabilir. Backend'e deploy GEREKMEDİ bu tur.
4. **Mobil dotlottie UX turu** (görev #5, hâlâ açık): dotlottie-flutter ile durum
   animasyonları + canlı checklist kartının görsel cilası. Fonksiyonel akış hazır;
   bu sadece görsel katman.
5. **device_not_found kök nedeni** (eski HANDOFF'tan taşınan): eşleşme kaybolması
   grace penceresiyle yamalandı ama backend'te cihaz lifecycle'ı hâlâ incelenmedi.
6. Kullanıcının genel hedefi: "her türlü görevi anlayıp sekmeden yerine getiren
   en geniş kabiliyetli runtime" — başarısız görev örnekleriyle (elyan tasks +
   daemon.log) düzenli tur atıp routing/planner/ajanı beslemeye devam et.

## Gotchas

- elyan reposunda website/*, DESIGN.md, PRODUCT.md BAŞKA bir oturumun işi —
  dokunma, commit'leme (working tree'de duruyor).
- Daemon'u restart etmek için `kill -9 <pid>` gerekebilirdi; SIGTERM düzeltmesi
  commit'lendi ama ÇALIŞAN daemon'da henüz test edilmedi — bir restart turunda doğrula.
- `browser_session` yetenekleri `allow_browser_control` iznine bağlı (tam yetki
  oturumu varsa otomatik açık). `file_move/make_directory` onaylı planlarda
  `_confirmed=True` ile çalışır (executor enjekte eder).
- websocket 4001 "replaced" = aynı cihazdan ikinci bağlantı; artık 3 sn bekleyip
  bağlanıyor. İki daemon süreci görürsen eskisini öldür.
- Mobil testte `POST /v1/mobile/world-signals failed` logları normaldir (mock).
- Backend testlerine dokunursan: env fixture'a yeni AppEnv alanı eklersen tüm
  fixture'ları güncelle (iyzico.test.ts kırılır).

## Komutlar

- Masaüstü test: `cd ~/Desktop/elyan && venv/bin/python3 -m pytest tests/ -q`
- Mobil test: `cd ~/Desktop/mobile-elyan && flutter test`
- Durum: `elyan status` · görevler: `elyan tasks`
- Log: `~/Library/Application Support/Elyan/state/daemon.log`
- State: `~/Library/Application Support/Elyan/state/elyan_state.json`
- Daemon restart: `kill -9 $(cat ~/Library/Application\ Support/Elyan/state/daemon.pid)`
  → launchd yeniden başlatır (SIGTERM fix doğrulanınca normal kill yeter).
