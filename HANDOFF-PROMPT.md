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

## 🔌 CONNECTORS — "Gmail'i bağla" tek dokunuş OAuth (SONRAKİ BÜYÜK İŞ, DETAYLI PLAN)

Hedef deneyim (ChatGPT/Claude connectors birebir): kullanıcı katalogdan
**Gmail** kartına dokunur → Google'ın OAuth ekranı açılır → hesabına girer →
bağlantı "Bağlı ✓" olur → Elyan görevlerinde Gmail araçları kullanılabilir.
URL yapıştırmak YOK; katalog küratörlüdür.

### Gerçekler (mimarî kararların dayanağı)
- MCP Python SDK **1.28.1 kurulu ve yeterli**: `mcp.client.streamable_http.
  streamablehttp_client` (uzak HTTP transport) + `mcp.client.auth.
  OAuthClientProvider, TokenStorage` (OAuth 2.1: PKCE, RFC 9728 korumalı
  kaynak metadata keşfi, RFC 7591 dinamik client kaydı) — bu oturumda import
  doğrulandı.
- İki tür servis var, İKİSİ AYRI KATMAN:
  - **A) Gerçek remote MCP sunucusu olanlar** (Notion `https://mcp.notion.com/mcp`,
    Linear `https://mcp.linear.app/sse`, Sentry, Asana, Atlassian...):
    OAuth'u MCP spec'i üzerinden kendileri konuşur → SDK provider'ı yeter.
  - **B) Resmî MCP'si OLMAYANLAR (Gmail/Google Takvim/Drive!)**: Google resmi
    MCP sunucusu yayınlamıyor. ChatGPT/Claude bunlara KENDİ OAuth client'ları
    + kendi gateway'leri ile bağlanır. Elyan da öyle yapmalı: backend
    connector-gateway (aşağıda). Üçüncü parti hosted Gmail-MCP'leri (Composio
    vb.) veriyi üçüncü partiden geçirir — ürün için ÖNERİLMEZ, plana alma.

### Katman A — Remote MCP connectors (runtime, ~1 gün)
1. `runtime/mcp_connectors.py` (YENİ): küratörlü katalog —
   `{id, name, icon, serverUrl, transport: "http", auth: "oauth", category}`.
   İlk liste: notion, linear, sentry, asana, atlassian, cloudflare, intercom,
   plaid, paypal, square, zapier. (Her birinin güncel MCP URL'ini uygulama
   sırasında sağlayıcı dokümanından doğrula; URL'ler değişebiliyor.)
2. `runtime/mcp_runtime.py`:
   - `normalize_server_config`: `transport: "http"` + `url` kabul et
     (şu an stdio-only reddediyor).
   - `_StateTokenStorage(server_id)` (TokenStorage impl): `get_tokens/
     set_tokens/get_client_info/set_client_info` → state
     `skills.mcpServers[i].auth = {tokens, clientInfo}` içinde saklar.
     NOT: uzun vadede macOS Keychain'e taşınacak; ilk sürümde state kabul
     (deviceSecret da orada), dosya izni 600 olduğundan emin ol.
   - `_with_session`: transport http ise
     `streamablehttp_client(url, auth=oauth_provider)`; stdio yolu aynen kalır.
     Daemon (başsız) bağlamda redirect/callback handler'ları interaktif
     OLAMAZ → token yoksa `SafeCapabilityError("MCP_AUTH_REQUIRED",
     "elyan connect <id> ile yetkilendir")`. Refresh token varsa provider
     sessizce yeniler (headless çalışır).
3. OAuth akışı (interaktif, CLI/daemon-dışı süreç):
   `run_connector_oauth(connector_id)` — 127.0.0.1'de geçici callback HTTP
   sunucusu (rastgele port, tek istek), `OAuthClientMetadata(redirect_uris=
   [o loopback URL], token_endpoint_auth_method="none", grant_types=
   ["authorization_code","refresh_token"], response_types=["code"],
   client_name="Elyan")`, `redirect_handler` = `webbrowser.open(auth_url)`,
   `callback_handler` = sunucudan code/state bekle (timeout 180 sn).
   Akış sonunda storage'a token düşer → sunucu configi `enabled: true` ile
   `skills.mcpServers`'a eklenir → `elyan mcp tools` ile araçlar görünür.
4. CLI: `elyan connect` (katalog listesi), `elyan connect notion` (akışı
   başlat), `elyan connections` (durum: Bağlı/Bağlı değil + araç sayısı),
   `elyan disconnect <id>` (token + sunucu kaydını sil).
5. Testler: TokenStorage state roundtrip; http config normalize; MCP_AUTH_REQUIRED
   headless hatası; katalog bütünlüğü (id benzersiz, url https). OAuth akışının
   kendisi için sahte AS ile entegrasyon testi (aiohttp/http.server tabanlı
   mini authorization server fixture) — SDK'nın test yardımcılarına bak.

### Katman B — Google (Gmail/Calendar/Drive) connector-gateway (backend + runtime, ~2-3 gün)
Google resmi MCP vermediği için OAuth client'ı ELYAN'a ait olmalı
(ChatGPT/Claude modeli). Parçalar:
1. **Google Cloud Console** (kullanıcı/işletme adımı — Emre yapacak):
   proje aç, OAuth consent screen (external, publishing), client tipi
   "Web application", redirect `https://api.elyan.dev/v1/connectors/google/callback`.
   Scope'lar minimum: `gmail.readonly`, `gmail.send`, `calendar.events`,
   `drive.readonly` (kademeli; ilk sürümde readonly+send yeter).
   client_id/secret backend env'ine (AppEnv) girer.
2. **Backend (`~/Desktop/elyan-backend`, yeni modül `src/modules/connectors/`)**:
   - `GET /v1/connectors` — katalog + kullanıcının bağlantı durumları.
   - `POST /v1/connectors/google/authorize` — state=JWT(userId, connectorId,
     nonce) ile Google auth URL üret, döndür.
   - `GET /v1/connectors/google/callback` — code'u token'a çevir, refresh
     token'ı KULLANICI hesabına ŞİFRELİ sakla (mevcut secret şifreleme
     altyapısı neyse onu kullan; yoksa libsodium sealed box + env master key),
     başarı sayfası göster ("Elyan'a dönebilirsin").
   - `POST /v1/connectors/google/token` — runtime/mobil için kısa ömürlü
     access token servis et (refresh backend'de kalır; access token cihaza
     iner, refresh token ASLA inmez).
   - `DELETE /v1/connectors/google` — bağlantıyı kes + Google token revoke.
   - Env fixture'larına yeni AppEnv alanlarını EKLEMEYİ UNUTMA (iyzico.test.ts
     kırılır — bilinen tuzak).
3. **Runtime**: `capability_spec.py`'a Google yetenekleri (Tek Spec ile —
   tek blok/yetenek): `gmail.search`, `gmail.read`, `gmail.send`
   (policy="confirm" + DISPATCH_AUTO_APPROVE_BLOCKLIST'e ekle),
   `calendar.google.list`, `drive.search`... Adapter modülü
   `actions/google_connector.py`: backend'den access token alır
   (`backend_client`'a `connector_token("google")` metodu), Google REST
   API'yi `requests` ile çağırır. Kanıt: sonuçlara `stateReadback` uyumlu
   alanlar (ör. gmail.send → `messageId` → readback observed).
4. **Mobil (chat-first!)**: ayrı ekran YOK — Ayarlar'daki "Bağlantılar"
   bölümü VE composer + menüsünde "Uygulama bağla" girişi bir SHEET açar:
   katalog kartları (ikon, ad, Bağla/Bağlı ✓/Kes). "Bağla" →
   `authorize` endpoint'inden URL → `ASWebAuthenticationSession` (SFAuthenticationSession
   değil) → callback backend'e döner → sheet durumu yeniler. Remote MCP
   (Katman A) bağlantıları cihaz-yerel olduğundan mobilde "Masaüstünde
   tamamla" düğmesi desktop'a bildirim/derin bağlantı yollar
   (`elyan connect <id>` tetiklenir) — v1'de bu kabul edilebilir.
5. **Planner/katalog**: bağlı connector araçları tool_catalog'a zaten düşer
   (MCP yolundan veya spec'ten). `elyan.cowork.v1` bağlamındaki yetenek
   adlarına gmail.* eklenince server_brain planlarında kullanılır.

### Güvenlik kuralları (pazarlıksız)
- Refresh token yalnız backend'de; cihaza kısa ömürlü access token iner.
- `gmail.send`, `drive.write` gibi dışa dönük eylemler: policy="confirm"
  + dispatch blocklist (telefondan açık onay).
- MCP/connector araç sonuçları kanıt sözleşmesine bağlı kalır
  (mcpToolExecuted / messageId readback).
- Loopback callback yalnız 127.0.0.1'e bind edilir; state/nonce doğrulanır;
  authorization code tek kullanımlık ve 3 dk timeout.
- Scope'lar kademeli istenir (incremental auth); "hepsini iste" YASAK.

### Uygulama sırası (önerilen)
1. Katman A (runtime-only, backend'siz kazanım): http transport + TokenStorage
   + `elyan connect notion` uçtan uca. → npm 1.7.0
2. Katman B backend gateway + `gmail.readonly/send` + mobil Bağlantılar sheet'i.
   → backend deploy + npm 1.8.0 + TestFlight
3. Katalog genişletme + Keychain göçü + revoke/health (bağlantı koptu rozetı).

## ⚠️ Kalanlar / sıradaki işler (öncelik sırası)

1. **npm publish 1.6.0** (sürüm bump'landı; tüm mimari turları içerir) — kod hazır, `npm pack` temiz (1.0 MB / 94 dosya).
   Kullanıcı kendisi yayınlamalı (2FA): `npm login` → `npm publish --otp=<kod>`
   → `npm install -g elyan@1.5.0 && elyan restart`. Kimlik bilgisi/OTP'yi
   Claude'a verme; kullanıcı terminalde kendi girer.
2. **Connectors planını uygula** (yukarıdaki 🔌 bölüm — Katman A'dan başla).
3. **Uçtan uca canlı test**: telefondan (a) "YouTube aç", (b) "Chrome'dan kedi
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
