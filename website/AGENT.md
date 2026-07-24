Elyan’ın mobil uygulamasının tam işlevli, responsive ve production-grade web sürümünü geliştir. Yalnız tasarım veya demo yapma; auth, chat, realtime, session history, görev yürütme, approval, typed widget/block sistemi, cihaz eşleştirme, ayarlar, billing ve integrations akışlarını gerçek backend’e bağla. Kodla, test et, preview ortamında doğrula ve bütün kabul kriterleri sağlanmadan işi tamamlandı sayma.

==================================================
1. ÇALIŞMA ALANI VE DEĞİŞMEZ SINIRLAR
==================================================

Ana web dizini:
- /Users/emrekoca/Desktop/elyan/website

Backend:
- /Users/emrekoca/Desktop/elyan-backend
- Yalnız web desteği için zorunlu, additive kontrat değişiklikleri yapılabilir.

Mobil referans:
- /Users/emrekoca/Desktop/mobile-elyan
- Mobil kodu salt-okuma referansı olarak kullan.
- Mobile UI veya Flutter koduna kesinlikle dokunma.

Desktop:
- /Users/emrekoca/Desktop/elyan/runtime
- Desktop runtime’a dokunma.
- Web hiçbir zaman desktop runtime’a doğrudan bağlanmayacak.

Değişmez akış:

Web UI
→ Elyan Web BFF
→ Elyan Backend/control-plane
→ server brain veya eşleştirilmiş desktop runtime

Kesinlikle yasak:

Web → Desktop runtime doğrudan
Web → local engine doğrudan
Web → browser/computer side effect doğrudan
Web → üçüncü parti connector API doğrudan

Backend; auth, session, routing, billing, devices, pairing, tasks, approvals, realtime ve orchestration truth sahibidir. Desktop yalnız backend tarafından yönlendirilmiş, izinli yerel işleri yürütür.

==================================================
2. CANLI WEBSITE REPO GERÇEĞİ
==================================================

Website artık Next.js veya React/Vite değildir.

Canlı stack:
- Astro 6
- TypeScript
- Tailwind CSS 4
- Preline UI
- GSAP

Önce şunları tamamen oku:
- website/.agents/AGENTS.md
- website/ROADMAP.md
- website/DESIGN.md
- website/astro.config.mjs
- website/package.json
- website/vercel.json
- website/src/assets/styles/global.css

Kurallar:

- React, Next.js, Vite, TSX veya JSX ekleme.
- Yalnız `.astro`, `.ts` ve veri için `.json` dosyaları kullan.
- Pazarlama sitesini yeniden yazma.
- Mevcut `/`, `/ozellikler`, `/nasil-calisir`, `/indir`, `/fiyatlandirma`, `/destek`, `/gizlilik`, `/kullanim-kosullari` sayfalarını koru.
- Authenticated uygulamayı ayrı `AppLayout` ve `/app/*` rotaları altında geliştir.
- Marketing navbar/footer/Lenis davranışlarını app shell’e taşıma.
- Web uygulamasında ayrı, sade ve mobil uygulamayla uyumlu bir shell kullan.

Önemli: Çalışma ağacı kirli ve Astro migration’ın birçok dosyası henüz untracked olabilir. Bunlar kullanıcı değişikliğidir.

- `git reset`, `git checkout --`, clean veya toplu silme yapma.
- Eski React/Vite dosyalarını geri getirme.
- Untracked Astro migration dosyalarını ezme veya silme.
- İlgisiz değişiklikleri düzenleme.
- npm kullan ve `package-lock.json`ı güncelle.
- Kullanıcı onayı olmadan `pnpm-lock.yaml` gibi mevcut dosyaları silme.
- Commit oluşturma; kullanıcı ayrıca istemedikçe commit atma.

==================================================
3. HEDEF ÜRÜN YAPISI
==================================================

Şu rotaları oluştur:

- `/app`
  - Auth/session resolver ve kısa splash.
  - Session varsa `/app/chat`.
  - Session yoksa `/app/login`.

- `/app/login`
  - E-posta/şifre
  - 2FA
  - Google
  - Apple
  - Güvenli `returnTo`

- `/app/register`
  - Ad soyad
  - E-posta
  - Şifre
  - Şifre doğrulama
  - Kullanım şartları
  - Gizlilik politikası
  - Opsiyonel AI veri paylaşımı izni
  - Google ile kayıt
  - Apple ile kayıt

- `/app/auth/callback`
  - Google/Apple callback sonucu
  - State/nonce doğrulaması
  - Güvenli başarı/hata yönlendirmesi

- `/app/chat`
  - Yeni sohbet
  - `?sessionId=` ile geçmiş session açma
  - `?taskId=` ile görev içeren session’a odaklanma

- `/app/pair`
  - Desktop pairing code girişi
  - Pairing sonucu ve desktop readiness

- `/app/settings`
  - Profil
  - Güvenlik
  - 2FA
  - Cihazlar
  - Desktop bağlantısı
  - Tercihler
  - Çıkış
  - Hesap silme

- `/app/settings/billing`
  - Planlar
  - Kullanım
  - Abonelik durumu
  - Checkout
  - Plan değiştirme/iptal

- `/app/integrations`
  - Backend’in sunduğu integrations/apps listesi
  - Connect/disconnect/probe
  - OAuth callback sonucu

- `/app/devices`
  - `/app/settings#devices` adresine güvenli yönlendirme

Önerilen dosya düzeni:

website/src/layouts/AppLayout.astro

website/src/pages/app/index.astro
website/src/pages/app/login.astro
website/src/pages/app/register.astro
website/src/pages/app/auth/callback.astro
website/src/pages/app/chat.astro
website/src/pages/app/pair.astro
website/src/pages/app/settings.astro
website/src/pages/app/settings/billing.astro
website/src/pages/app/integrations.astro

website/src/pages/app/api/auth/login.ts
website/src/pages/app/api/auth/register.ts
website/src/pages/app/api/auth/google.ts
website/src/pages/app/api/auth/apple.ts
website/src/pages/app/api/auth/refresh.ts
website/src/pages/app/api/auth/logout.ts
website/src/pages/app/api/auth/session.ts
website/src/pages/app/api/realtime/stream.ts
website/src/pages/app/api/backend/[...path].ts

website/src/components/app/auth/*
website/src/components/app/chat/*
website/src/components/app/composer/*
website/src/components/app/history/*
website/src/components/app/tasks/*
website/src/components/app/approvals/*
website/src/components/app/blocks/*
website/src/components/app/settings/*
website/src/components/app/shared/*

website/src/lib/api/client.ts
website/src/lib/api/errors.ts
website/src/lib/api/idempotency.ts
website/src/lib/auth/auth-controller.ts
website/src/lib/auth/auth-guard.ts
website/src/lib/auth/oauth-transaction.ts
website/src/lib/realtime/sse-controller.ts
website/src/lib/state/store.ts
website/src/lib/state/chat-controller.ts
website/src/lib/state/session-controller.ts
website/src/lib/contracts/generated/*
website/src/lib/blocks/registry.ts
website/src/lib/blocks/parser.ts
website/src/lib/blocks/stream-reducer.ts
website/src/lib/security/safe-url.ts
website/src/lib/security/safe-markdown.ts
website/src/lib/config.ts

==================================================
4. DEPLOYMENT VE BFF KARARI
==================================================

Authenticated web uygulamasını salt statik Hostinger sayfası olarak yayınlama. Refresh token’ın güvenli tutulması ve authenticated SSE için server-capable Astro deployment gereklidir.

Önerilen production yüzeyi:
- `app.elyan.dev`
- Astro server mode
- Resmî `@astrojs/vercel` adapter
- Marketing sayfaları prerender edilmeye devam eder.
- `/app/*` ve `/app/api/*` server-capable çalışır.

Alternatif Node deployment kullanılacaksa yalnız mevcut altyapı bunu gerektiriyorsa resmî `@astrojs/node` adapter kullan.

BFF akışı:

Browser
→ same-origin `/app/api/*`
→ BFF, HttpOnly cookie’den Elyan token’ını alır
→ `https://api.elyan.dev/v1/*` upstream çağrısı
→ Güvenli response browser’a döner

Kurallar:

- Browser’a refresh token gönderme.
- Access veya refresh token’ı `localStorage`, `sessionStorage`, IndexedDB, URL, query string veya JS global state içine koyma.
- Backend’den dönen `tokens` alanını browser response’una taşımadan önce çıkar.
- Tokenlar yalnız:
  - `HttpOnly`
  - `Secure`
  - `SameSite=Lax`
  - uygun dar `Path`
  cookie’lerinde yaşasın.
- Cookie adlarında `__Secure-` prefix kullan.
- Logout sırasında cookie’leri her durumda temizle.
- Auth response’ları `Cache-Control: no-store` olsun.
- BFF credentials, ID token, authorization code veya token loglamasın.

BFF açık proxy olmamalı.

Yalnız açık allowlist’teki method/path çiftlerini proxy et:

- `/v1/auth/*`
- `/v1/web/bootstrap`
- `/v1/mobile/bootstrap` yalnız geçici compatibility
- `/v1/chat/*`
- `/v1/tasks/*`
- `/v1/devices/*`
- `/v1/pairing/*`
- Kullanıcıya açık `/v1/billing/*` rotaları
- Kullanıcıya açık `/v1/integrations/*` rotaları

Admin, runtime registration, webhook, billing callback, internal MCP veya desktop secret rotalarını browser proxy’sine açma.

BFF:

- Client’ın Authorization header’ını kabul etmemeli.
- Kendi HttpOnly cookie token’ını kullanmalı.
- Hop-by-hop header’ları temizlemeli.
- `Idempotency-Key`, `If-None-Match`, `Last-Event-ID`, `Content-Type` gibi gerekli header’ları allowlist ile taşımalı.
- `x-request-id`, `etag`, `retry-after` alanlarını güvenli şekilde browser’a aktarmalı.
- Her upstream isteğe timeout/AbortController uygulamalı.
- Client bağlantısı kesilince SSE upstream bağlantısını kapatmalı.
- URL/path parametrelerini validate etmeli.
- Arbitrary upstream URL kabul etmemeli.
- SSRF oluşturabilecek URL parametresi kullanmamalı.

State-changing BFF çağrılarında:

- Origin doğrulaması
- Double-submit CSRF token
- `X-CSRF-Token`
- SameSite cookie
- JSON content-type kontrolü

kullan.

==================================================
5. BACKEND WEB PREREQUISITE DEĞİŞİKLİKLERİ
==================================================

Backend’de aynı auth/session/task mantığını yeniden yazma. Yalnız mevcut servisleri kullanan additive web desteği ekle.

Gerekli değişiklikler:

1. Chat/task source enum’larına additive `web` değeri ekle.

Mevcut mobile ve desktop değerlerini bozma:
- `mobile`
- `desktop`
- yeni: `web`

Backend schema, domain type, test ve audit alanlarını birlikte güncelle.

2. `GET /v1/web/bootstrap` ekle.

Bu endpoint yeni bootstrap mantığı yazmamalı. Mevcut mobile bootstrap servisindeki:

- user
- billingState
- quota
- subscription
- usage
- brain
- devices
- summary

truth’unu web için yeniden kullansın.

`recentTasks` veya `historyFeed` boş gelebilir; web history bunlara güvenmemeli. Session ve task listeleri kendi endpointlerinden cursor ile alınmalı.

3. OAuth schema’ya gerektiğinde optional web transaction alanları ekle:

- `nonce`
- güvenli state transaction kimliği

Backend ID token doğrulamasında:

- signature
- issuer
- audience
- expiration
- nonce

kontrol edilsin.

4. Google Web Client ID, backend’in kabul ettiği Google audience listesinde bulunsun.

5. Apple Service ID, backend `APPLE_SERVICE_ID` audience listesinde bulunsun.

6. Mobile bearer auth kontratını değiştirme. Web BFF mevcut bearer kontratının server-side tüketicisidir.

7. Password reset/email verification backend’de mevcut değilse sahte çalışan buton üretme.

Forgot-password özelliğini yayınlamak istersen:

- Tek kullanımlık
- Hash’lenmiş
- Süreli
- Rate-limitli
- E-posta var/yok bilgisini sızdırmayan
- Transactional email adapter arkasında

gerçek backend desteğiyle birlikte tamamla.

E-posta gönderim altyapısı/credential yoksa inactive modal bırakma; kontrolü gizle ve final raporda dış servis prerequisite’i olarak belirt.

==================================================
6. AUTHENTICATION AKIŞI
==================================================

Upstream backend:

POST `/v1/auth/register`

```json
{
  "displayName": "Emre Koca",
  "email": "emre@example.com",
  "password": "minimum8",
  "legalAcceptance": {
    "termsAccepted": true,
    "privacyAccepted": true,
    "aiDataSharingAccepted": false
  }
}
POST /v1/auth/login
{
  "email": "emre@example.com",
  "password": "minimum8",
  "twoFactorCode": "123456"
}
POST /v1/auth/oauth/google
POST /v1/auth/oauth/apple
{
  "idToken": "...",
  "authorizationCode": "...",
  "email": "optional@example.com",
  "displayName": "Optional",
  "nonce": "...",
  "legalAcceptance": {
    "termsAccepted": true,
    "privacyAccepted": true,
    "aiDataSharingAccepted": false
  }
}
Diğer auth rotaları:
POST /v1/auth/refresh
POST /v1/auth/logout
GET /v1/auth/me
PATCH /v1/auth/me
POST /v1/auth/password
GET /v1/auth/2fa/status
POST /v1/auth/2fa/setup
POST /v1/auth/2fa/enable
POST /v1/auth/2fa/disable
DELETE /v1/auth/me
Web login davranışı:
Email validation
Password min 8
autocomplete="email"
autocomplete="current-password"
Double-submit engeli
Loading state
Safe inline error
Backend requestId’i debug için kopyalanabilir göster
Raw details/stack gösterme
two_factor_required gelirse erişilebilir 6 haneli 2FA ekranına geç
two_factor_invalid gelirse session’ı silmeden tekrar sor
Register:
Display name minimum 2
Email
Password min 8
Confirm password
Terms ve Privacy ayrı ayrı zorunlu
AI data sharing ayrı ve opsiyonel
Checkbox’lar önceden seçili gelmemeli
Legal linkler:/kullanim-kosullari
/gizlilik

Social signup öncesinde de legal acceptance alınmalı.
Login ekranındaki gibi körlemesine termsAccepted=true gönderme.
Google:
Resmî Google Identity Services kullan.
Eski Google Sign-In kütüphanesini kullanma.
Authentication için yalnız ID token al.
Giriş anında Gmail/Drive/Calendar scope isteme.
Connector authorization daha sonra, kullanıcı ilgili entegrasyonu açtığında istenmeli.
ID token BFF’ye gönderilsin.
Backend signature/audience/issuer/expiry/nonce doğrulasın.
Google client secret browser’a konmasın.
One Tap kullanılacaksa kullanıcı kontrolünü bozmayacak ve dismiss state’ine saygılı olacak şekilde yap.
Apple:
Resmî Sign in with Apple JS kullan.
Web için Apple Service ID kullan.
HTTPS redirect URI kullan.
state ve nonce crypto-secure oluştur.
Kısa süreli auth transaction cookie’sine bağla.
Popup akışını tercih et.
Dönen ID token, authorization code, ilk seferde gelebilen email/name BFF üzerinden backend’e gönderilsin.
Apple private key/client secret browser’a asla konmasın.
Mevcut backend Apple callback yalnız landing page ise bunu “çalışıyor” sayma; popup veya tamamlanmış callback exchange ile gerçek session üret.
Resmî belgeler:
https://developers.google.com/identity/gsi/web/guides/overview
https://developers.google.com/identity/gsi/web/guides/verify-google-id-token
https://developer.apple.com/documentation/signinwithapple/configuring-your-webpage-for-sign-in-with-apple
https://developer.apple.com/documentation/signinwithapple/sign_in_with_apple_js
https://docs.astro.build/en/guides/endpoints/
https://docs.astro.build/en/guides/integrations-guide/vercel/
Auth controller:
Startup’ta session restore doğrulaması bitmeden protected shell gösterme.
Session yoksa /app/login.
Geçerli session varsa /app/chat.
Backend 401 authoritative ise session’ı temizle.
Network timeout/5xx yüzünden session’ı hemen silme; offline/degraded state göster.
Access token bitimine yaklaşık 90 saniye kala refresh et.
Refresh single-flight olsun.
Birden fazla tab için BroadcastChannel ve mümkünse Web Locks API kullan.
Logout local-first olsun:UI/auth state’i temizle.
SSE kapat.
Chat/device/bootstrap state’i temizle.
BFF cookie’lerini temizle.
Backend logout best-effort.
/app/login yönlendirmesi.

Diğer sekmelere logout olayı yayınla.
Safe redirect:
returnTo yalnız /app/ iç rotalarını kabul etsin.
http:, https:, //, başka origin, javascript:, encoded path traversal ve açık redirect reddedilsin.
Login sonrası yalnız allowlisted route’a git.
==================================================
7. CHAT, SESSION VE TASK AKIŞI
==================================================
Web composer doğal dil görevlerini doğrudan /v1/tasks ile başlatmamalı.
Canonical gönderim:
POST /v1/chat/messages
Örnek:
{
  "sessionId": "optional-uuid",
  "targetDeviceId": "optional-desktop-uuid",
  "source": "web",
  "blocks": [
    {
      "type": "text",
      "markdown": "Chrome'u kapat"
    }
  ],
  "requestedCapabilities": [],
  "metadata": {
    "renderContract": {
      "version": "elyan_blocks.v2",
      "mode": "block_first",
      "canonicalSurface": "blocks",
      "legacyContent": "none"
    }
  }
}
Header:
Idempotency-Key
8–160 karakter
Aynı optimistic message retry edilirken aynı key korunmalı.
Session rotaları:
GET /v1/chat/sessions?status=active&cursor=&limit=20
GET /v1/chat/sessions?status=archived&cursor=&limit=20
POST /v1/chat/sessions
GET /v1/chat/sessions/:sessionId
GET /v1/chat/sessions/:sessionId/messages?cursor=&limit=50
PATCH /v1/chat/sessions/:sessionId
DELETE /v1/chat/sessions/:sessionId
DELETE /v1/chat/sessions?before=...
Kurallar:
History task listesi değil, chat session listesidir.
Launch sırasında yalnız hafif session özetlerini getir.
Mesajları session açılınca lazy/cursor pagination ile getir.
Task’lar session timeline’ın içinde görünür.
Task row’larını ayrı chat history kaydı gibi gösterme.
Optimistic user message ekle.
Backend’den gelen gerçek session/message/task ID’leriyle reconcile et.
Aynı idempotency key ile duplicate mesaj oluşturma.
Session rename/archive/restore/delete destekle.
Delete öncesi erişilebilir confirmation kullan.
Yeni chat açıldığında önceki SSE/task subscription’larını doğru şekilde kapat.
Task rotaları yalnız lifecycle/detail/action için:
GET /v1/tasks
GET /v1/tasks/:taskId
POST /v1/tasks/:taskId/cancel
POST /v1/tasks/:taskId/approval
POST /v1/tasks/:taskId/feedback
Artifact endpointleri
Approval payload:
{
  "approved": true,
  "notes": "optional"
}
Task durumları:
queued
planning
waiting_for_device
running
waiting_approval
completed
failed
canceled
Inline task card şunları göstermeli:
Current status
Progress
Gerçek capability/target
Approval nedeni
Risk
Plan revision
Exact app/file/action hedefi
Approve/reject
Cancel
Safe error
Artifact/result
Retry veya desktop connection önerisi
Web kendi kendine browser/computer action yapmamalı. Approval yalnız backend endpointine gider.
==================================================
8. DEVICE VE PAIRING
==================================================
Device truth:
GET /v1/devices
Yalnız şu desktop görev hedefi olarak seçilebilir:
type === "desktop"
canReceiveTasks === true
UI’da ayrıca göster:
isOnline
realtimeReady
targetStatus
targetErrorCode
runtime readiness
son görülme
device label
selectedDeviceId tek başına her mesajı desktop’a zorlamamalı. Routing backend truth’udur.
Pairing:
POST /v1/pairing/sessions/claim-by-code
Girdi: pairing code
Sonuç: claimed desktopDeviceId
Browser’a hiçbir zaman şunları gönderme/gösterme:
deviceSecret
runtime secret
desktop inbound address
local runtime token
Desktop offline ise görev kartında açıkça:
“Masaüstü çevrimdışı”
“Bağlantı bekleniyor”
“Başka cihaz seç”
“Eşleştir”
durumları göster.
==================================================
9. REALTIME SSE
==================================================
Upstream:
GET /v1/realtime/stream
Opsiyonel taskId
Opsiyonel deviceId
İkisi aynı anda kullanılamaz.
Cursor veya Last-Event-ID ile devam eder.
Browser doğrudan bearer EventSource açmayacak. Same-origin BFF stream proxy kullan:
Browser:
/app/api/realtime/stream?...
BFF:
HttpOnly access cookie’yi alır.
Upstream’e Authorization: Bearer ... ekler.
Last-Event-ID ve cursor’ı taşır.
text/event-stream
Cache-Control: no-cache, no-transform
buffering kapalı
disconnect propagation
heartbeat passthrough
İşlenecek event aileleri:
ready
heartbeat
resync_required
message.created
message.delta
message.completed
message.error
block.preview
usage.final
task lifecycle/status/artifact/approval eventleri
SSE controller:
eventId/cursor saklar
generation fencing kullanır
duplicate event’i tekrar uygulamaz
exponential backoff + jitter ile reconnect eder
server retry değerine saygı duyar
visibility/offline durumunu hesaba katar
401’de stream’i kapatır, auth refresh yapar, bir kez tekrar bağlanır
resync_required geldiğinde delta tahmini yapmaz; REST’ten authoritative session/task snapshot çeker
Completed mesajı geç gelen running/delta event’iyle geri düşürmez
Terminal state monotonic merge kullanır
Aynı kullanıcı için kontrolsüz çoklu stream açmaz
==================================================
10. TYPED WIDGET / BLOCK SİSTEMİ
==================================================
Elle yeni block union yazma.
Tek handwritten source:
/Users/emrekoca/Desktop/elyan-backend/src/contracts/assistant-block-schemas.ts
Generated source:
/Users/emrekoca/Desktop/elyan-backend/contracts/generated/assistant-blocks.schema.json
Web build:
Backend generated JSON schema’yı sync et.
TypeScript type/model üret.
Runtime validation için AJV kullan.
Schema SHA-256 drift gate ekle.
Backend schema değiştiğinde web CI drift yüzünden fail etsin.
Generated dosyaları elle düzenleme.
Canonical block:
{
  "type": "status",
  "version": 1,
  "blockId": "runtime:status:task-123",
  "stableBlockId": "runtime:status:task-123",
  "source": "runtime",
  "visibility": "user_visible",
  "renderHints": {
    "density": "compact",
    "sectionRole": "status"
  },
  "data": {
    "status": "running",
    "message": "Chrome kapatılıyor"
  },
  "cacheDigest": "digest",
  "isRenderable": true
}
Renderer pipeline:
assistantMessage
→ blocks[] var mı?
→ schema validate
→ visibility/isRenderable gate
→ canonical data normalize
→ central BlockRegistry
→ type-specific renderer
→ safe unknown fallback
Ana kural:
blocks[] varsa görünür truth odur.
content yalnız blocks yoksa veya hiçbir render edilebilir block yoksa legacy fallback’tir.
Aynı mesajda typed block ve legacy content’i birlikte gösterme.
data canonical payload’dur.
Legacy flat fields yalnız backward-compatible fallback.
visibility === "assistant_internal_by_default" ise render etme.
isRenderable === false ise render etme.
Internal reasoning/security/task trace backend tarafından public payload’dan çıkarılmışsa yeniden üretmeye çalışma.
Raw chain-of-thought gösterme.
Central registry tek dosyada type → renderer mapping tutsun.
Desteklenecek block aileleri:
Prose:
text
summary
next_steps
Lifecycle/action:
status
actionable
clarification
capability_unavailable
task_trace yalnız public-safe gelirse
tool_call
Structured:
code
table
chart
math
math_surface_3d
svg
web_search
Files/documents:
file
artifact
document_block
document_block_skeleton
pdf_generate
pdf_viewer
Attachment/vision:
attachment_context
context_signal
attachment_ack
image_analysis
vision
Goals/personalization:
goal_progress
memory_echo
proactive_touch
desktop_suggestion
automation
Connector widgets:
mail_list
mail_detail
calendar_agenda
drive_files
notion_page
github_activity
slack_messages
Legacy read-only:
connector_result
Yeni connector_result üretme; yalnız eski history için parse et.
Source widgets:
data.state = loading | ready | empty | error
Error yalnız safe shape:
{
  "code": "SAFE_ERROR_CODE",
  "message": "Kullanıcıya uygun kısa mesaj"
}
Streaming block reducer:
Identity: messageId + blockId
blockId yoksa stableBlockId
Son çare deterministic legacy ID
Server block array snapshot’ı authoritative
block_delta: yalnız hedef block’u güncelle
block_replace: yalnız hedef block’u değiştir
block_status: yalnız izinli status alanlarını merge et
Hedef bulunamazsa tüm history’yi yeniden yaratma
Server sırasını koru
Terminal status geri düşmesin
cacheDigest değişirse ilgili block rerender olsun
React key mantığı kullanma; framework yok. DOM identity data-block-id ile yönetilsin.
Streaming sırasında yalnız aktif text block animasyonlu güncellensin.
Completed snapshot gelince geçici preview/delta truth’un üzerine yazsın.
Unknown block:
Uygulama crash olmamalı.
Raw JSON gösterme.
Terminal mesajda compact “Bu içerik türü için uygulama güncellemesi gerekiyor” fallback’i göster.
Streaming sırasında invalid/unknown source block sessizce bekletilebilir.
Telemetry’ye yalnız type ve safe error code yaz.
Block actions:
İzinli canonical action tipleri:
link.open
mail.open
calendar.menu
Action shape:
{
  "type": "link.open",
  "blockId": "...",
  "source": "web",
  "targetId": "optional",
  "url": "https://...",
  "payload": {}
}
Kurallar:
URL yalnız https: veya gerektiğinde güvenli http:.
javascript:, data:, file:, custom scheme reddedilsin.
External link noopener noreferrer.
mail.open ve calendar.menu arbitrary fetch’e çevrilmesin.
Backend action gerekiyorsa yeni chat message metadata içindeki blockAction üzerinden gönder.
Block verisine bakarak connector write işlemi doğrudan çağırma.
Side effect yine task/approval akışından geçsin.
XSS:
Markdown sanitize edilmeden HTML’e çevrilmesin.
Raw HTML varsayılan olarak kapalı olsun.
SVG sanitize edilmeden DOM’a konmasın.
Code block hiçbir zaman çalıştırılmasın.
Table/chart label’ları text olarak işlensin.
File/artifact URL’leri ownership-checked BFF proxy veya backend signed URL üzerinden açılsın.
innerHTML yalnız merkezi sanitizer’dan geçmiş trusted output için kullanılabilir.
Kütüphaneler:
AJV: generated JSON schema validation
DOMPurify: HTML/SVG sanitation
Marked veya markdown-it: markdown parser
KaTeX: math, lazy-load
Chart.js: chart, lazy-load
Playwright: E2E
Vitest: unit/contract tests
axe-core: accessibility gate
Gereksiz büyük UI framework’ü ekleme.
==================================================
11. RESPONSIVE MOBİL-WEB TASARIMI
==================================================
Web app, marketing sitesinin purple tasarımını körlemesine kullanmayacak. Uygulama yüzeyi mobil Elyan tasarımına yakın olacak ve CSS token’ları .elyan-app-root altında izole edilecek.
Mobil referans renkleri:
background: #FAF7F1
backgroundDeep: #EBDFCF
surface: #FCF8F2
surfaceMuted: #F3EADD
outline: #E2D4C2
primary: #6F8B6D
primaryDark: #566A55
primarySoft: #E7EEE0
accent: #5A7D77
text: #171717
textMuted: #666666
success: #557E58
warning: #AC7A4A
danger: #A86148
App styles marketing global token’larını bozmasın.
Breakpoint davranışı:
<390px: compact phone
390–459px: standard phone
460–759px: large phone
760–919px: tablet
>=920px: wide web
>=1180px: desktop shell
Layout:
Mobil:
Tek kolon
Sidebar overlay/drawer
Drawer yaklaşık %72, max 340px
Sabit alt composer
Safe-area inset
VisualViewport/keyboard handling
Minimum 44px touch target
Yatay scroll yok
Tablet:
Overlay veya collapsible sidebar
Chat max width yaklaşık 840px
Composer chat genişliğiyle hizalı
Desktop:
Persistent/collapsible 280–320px sidebar
Ortalanmış 840–980px chat surface
Gerekirse sağda 300–340px task inspector
Geniş ekranda mesaj satırlarını gereksiz uzatma
Chat empty state:
“Merhaba {ad}”
“Nasılsın bugün?”
Yeni görev önerileri
Composer ana odak
Desktop status sade şekilde görünür
Composer:
Multiline autosize
Enter gönder, Shift+Enter yeni satır
IME composition korunmalı
Send double-submit engeli
Attachment
Cancel generation/task
Rate-limit ve offline state
Dosya drop
Mobil keyboard açıldığında görünür kalma
aria-label
Focus restore
Sidebar:
Yeni sohbet
Active sessions
Archived sessions
Infinite/cursor pagination
Rename
Delete confirm
Desktop connection
Integrations
Settings
Profile/logout
Auth yüzeyleri:
Max form width yaklaşık 540px
Keyboard-safe scroll
Açık ve ferah
Marketing navbar/footer yok
Apple ve Google resmî branding kurallarına uygun
Loading sırasında layout shift yok
Hata form alanına bağlanmış
Screen reader announcement
Accessibility:
WCAG 2.2 AA
Kontrast en az 4.5:1
Tam keyboard navigation
Visible focus
Dialog focus trap
Escape close
aria-live progress ve hata bölgeleri
Reduced motion
Text zoom %200
Screen reader labels
Color tek durum göstergesi olmamalı
Motion:
150–250ms
Ölçülü
prefers-reduced-motion
Chat streaming sırasında ağır GSAP animasyonu yok
Uzun history listesinde sürekli blur/backdrop animation yok
UI performansını düşürecek büyük glass efektleri mobilde azalt
==================================================
12. SETTINGS, BILLING VE INTEGRATIONS
==================================================
Settings gerçek backend’e bağlı olsun.
Profil:
GET /v1/auth/me
PATCH /v1/auth/me
Avatar endpointleri mevcut kontrattan
Password change
2FA setup/enable/disable
Account delete
Logout
Billing:
GET /v1/billing/plans
GET /v1/billing/summary
GET /v1/billing/profile
POST /v1/billing/checkout/init
GET /v1/billing/checkouts/:referenceId
GET /v1/billing/checkouts/:referenceId/launch
POST /v1/billing/subscription/change-plan
POST /v1/billing/subscription/cancel
POST /v1/billing/trials/pro/claim
Webhook veya billing callback rotalarını browser proxy allowlist’ine ekleme.
Integrations:
GET /v1/integrations/apps
POST /v1/integrations/apps/:appId/oauth/start
DELETE /v1/integrations/apps/:appId
POST /v1/integrations/apps/:appId/probe
OAuth callback
Status/error/reconnect
Connector login ile Elyan account login’i karıştırma.
Google ile Elyan’a giriş yapmak:
Authentication
Gmail/Drive/Calendar bağlamak:
Ayrı authorization
Ayrı scope
Kullanıcı ilgili entegrasyonu açtığında
Connector write action’ları doğrudan çalıştırma; task/approval akışından geçir.
==================================================
13. ATTACHMENT VE PRIVACY
==================================================
Browser yalnız kullanıcı açıkça dosya seçtiğinde erişebilir.
Drag/drop ve file picker
Boyut/type validation
Preview URL cleanup
EXIF/metadata stripping mümkünse client-side
Raw private dosya varsayılan olarak backend’e yüklenmez
Önce browser’da parse/OCR/chunk mümkünse DocumentEnvelope üret
Cloud vision veya raw media paylaşımı ayrı açık consent gerektirir
Consent kapalıysa private content browser/desktop sınırında kalır
File name/path telemetry’ye yazılmaz
Browser fake local path’i backend’e göndermesin
Desktop filesystem path’i browser’dan tahmin etmeye çalışma
Artifact download yalnız ownership-checked backend/BFF akışından gelsin
Blob URL’lerini component dispose sırasında revoke et
==================================================
14. API CLIENT DAVRANIŞI
==================================================
Typed API client:
Structured result/error
AbortController timeout
Request ID
ETag/If-None-Match
Idempotency-Key
Retry-After
Safe error mapping
One auth retry
Single-flight refresh
Network/offline detection
Retry:
Retry et:
network disconnect
timeout
502
503
uygun 429, Retry-After ile
Retry etme:
400
401, refresh başarısızsa
403
404
409
422
destructive/non-idempotent request, idempotency key yoksa
Backoff:
bounded exponential
jitter
sonsuz retry yok
UI’da gerçek durum görünür
Backend hata shape’i:
{
  "error": "safe_code",
  "message": "Safe message",
  "details": {},
  "requestId": "..."
}
details içinden raw stack, SQL, provider token veya internal path gösterme.
==================================================
15. CSP, CACHE VE WEB GÜVENLİĞİ
==================================================
Mevcut vercel.json bütün route’lara public cache ve connect-src 'self' uyguluyor. App için düzelt.
/app/* ve /app/api/*:
Cache-Control: no-store
frame-ancestors 'none'
object-src 'none'
base-uri 'self'
sıkı form-action
Google/Apple için yalnız gerekli script/frame origin’leri
unsafe-eval kaldır
Inline script gerekiyorsa nonce/hash kullan
Blob preview gerekiyorsa yalnız gerekli blob: izinleri
Signed artifact hostunu exact allowlist et
Wildcard source kullanma
Marketing static asset’leri public immutable cache kullanabilir.
Ek güvenlik:
Open redirect testi
CSRF testi
XSS block fixtures
Malicious markdown
Malicious SVG
javascript URL
Oversized block payload
Unknown block
OAuth replay/state mismatch
Cookie flags
Token storage taraması
BFF path traversal/SSRF
Clickjacking
Rate-limit UI
==================================================
16. PWA VE MOBİL WEB
==================================================
Mevcut manifest sistemini /app için tamamla:
start_url /app
scope /app/
display standalone
theme/background colors
doğru icons
iOS web app meta alanları
safe-area desteği
Service worker kullanılırsa:
Yalnız app shell/static asset cache
Auth response cache yok
Chat/session/task/API response cache yok
Private artifact cache yok
Logout sırasında app state temizlenir
Offline’da eski private mesajları kontrolsüz göstermesin
Background hidden action çalıştırmasın
==================================================
17. TEST VE KABUL KRİTERLERİ
==================================================
Unit/contract testleri:
Auth:
Signed-out startup → login
Signed-in startup → chat
Safe returnTo
Open redirect reddi
Login/register validation
2FA required/invalid
Google success/cancel/error
Apple success/cancel/state mismatch
Legal acceptance required
Token hiçbir browser storage’da yok
Refresh single-flight
Multi-tab logout
401 logout
5xx/offline session’ı yanlışlıkla silmiyor
Local-first logout
BFF:
HttpOnly/Secure/SameSite cookies
Token response’tan çıkarılıyor
CSRF
Origin validation
Proxy allowlist
SSRF/path traversal
Upstream timeout
RequestId/ETag/Retry-After
SSE streaming/disconnect
Token/credential loglanmıyor
Chat:
Session list cursor pagination
Lazy message pagination
New session
Optimistic message
Backend ID reconciliation
Stable Idempotency-Key retry
Rename/archive/delete
Task session timeline’da
Duplicate task history row yok
Desktop offline
Approval/cancel
Rate limit
Realtime:
Last-Event-ID
Cursor persistence
Event dedup
Generation fence
Reconnect+jitter
resync_required → REST snapshot
Terminal state monotonic
Completed mesaj geç delta ile bozulmuyor
Tek aktif stream
Blocks:
Generated schema digest gate
Her canonical block tipi
Connector loading/ready/empty/error
blocks[] content’e üstün
Legacy content yalnız fallback
Duplicate visible text yok
visibility internal gizli
isRenderable false gizli
messageId+blockId upsert
delta/replace/status
Authoritative snapshot
Unknown block safe fallback
Invalid block crash yok
Malicious markdown/SVG/URL
Code execute edilmiyor
Block action allowlist
Responsive Playwright viewports:
320×568
375×812
390×844
768×1024
1024×768
1440×900
Her viewport’ta:
Horizontal overflow yok
Composer görünür
Keyboard/focus akışı
Sidebar doğru modda
Dialog taşmıyor
Typed widgets okunabilir
Table/code block kendi kontrollü scroll alanında
Touch target en az 44px
Safe-area uygulanmış
E2E:
Register
Legal acceptance
Login
2FA
Google mock flow
Apple mock flow
/v1/auth/me
Bootstrap
Session history
Yeni mesaj
SSE delta
Typed block completed snapshot
Desktop task
Approval
Completion/artifact
Settings/profile
Pairing
Billing summary
Integration connect/disconnect
Logout/protected redirect
Accessibility:
axe-core serious/critical violation yok
Keyboard-only flow
Screen reader labels
Reduced motion
Backend değiştiyse:
Backend typecheck
Auth tests
Chat schema tests
Web bootstrap tests
OAuth nonce tests
Existing mobile/desktop contract tests
Web final gate:
npm run format:check
npm run astro check veya eşdeğer typecheck
npm run test
npm run test:e2e
npm run build
git diff --check
Ayrıca:
Mevcut marketing route smoke testleri
/app/* protected route smoke
Preview deployment
CSP/header doğrulaması
Cookie flag doğrulaması
Gerçek backend authenticated smoke
Production tamamlanma smoke’u:
Email register/login veya Google/Apple
/v1/auth/me
/v1/web/bootstrap
Session listesini çek
Session mesajlarını lazy yükle
Web’den doğal dil mesajı gönder
SSE ile assistant response al
Typed blocks render et
Paired desktop’a görev yönlendir
Approval ver
Task completion/artifact göster
Logout
Protected route login’e dönüyor
Browser storage’da token yok
==================================================
18. ÇALIŞMA DİSİPLİNİ
==================================================
Analizle yetinme.
Tasarım mockup’ıyla bırakma.
Inert buton bırakma.
Sahte API veya production fallback bırakma.
TODO ile kritik akış bırakma.
Bir fazın testleri yeşil olmadan sonraki fazı “tamamlandı” sayma.
Existing mobile/backend contracts’i kopyala, yeni paralel protokol üretme.
Backend schema’yı elle web’e fork etme.
Mobile veya desktop runtime’ı değiştirme.
Marketing siteyi bozma.
External credential eksikse diğer bütün işleri bitir ve yalnız exact credential/deployment blocker’ını raporla.
Production deploy yetkisi yoksa preview deploy ile doğrula; yetkisiz production deploy yapma.
Kullanıcıdan yalnız gerçekten gerekli secret/domain/OAuth-console ayarı için soru sor.
Teknik kararlar için onay bekleme; mevcut kurallara göre ilerle.
Final rapor:
Uygulanan mimari
Web→BFF→Backend→Desktop akışı
Auth ve OAuth çözümü
BFF/cookie güvenliği
Route listesi
Block/widget registry
Backend’de yapılan additive değişiklikler
Değişen dosyalar
Eklenen kütüphaneler ve resmî kaynakları
Test sonuçları
Preview URL
Kalan gerçek external blocker
Mobile, desktop ve marketing siteye dokunulmadığının doğrulaması
Bütün kabul kriterleri tamamlanmadan “tamamlandı” deme. Şimdi canlı kodu inceleyip doğrudan uygulamaya başla.