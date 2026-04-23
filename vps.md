# Elyan VPS

Snapshot date: `2026-04-23`

Bu dosya `api.elyan.dev` arkasındaki VPS kontrol düzleminin mevcut, canlı ve dürüst durumunu anlatır. Amaç:

- sunucuda ne var, ne yok
- PostgreSQL'de hangi truth saklanıyor
- auth, billing, device sync ve release akışları nasıl çalışıyor
- local runtime ile VPS truth'un sınırı nerede
- mevcut gerçek blokaj ne

Bu doküman bir ürün özeti değil; operasyonel gerçek kaydıdır.

## Kısa Model

Elyan üç katmanlı çalışır:

1. `local-first runtime`
2. `shared VPS control plane`
3. `hosted web surface`

VPS yalnızca ortak truth tutar:

- auth ve session
- subscriptions
- billing
- entitlements
- credit/token ledger
- notifications
- device sync metadata
- release/download metadata

VPS, kullanıcının özel yerel belleği, dosyaları veya lokal aksiyon geçmişi için kalıcı depo değildir.

## Canlı Sunucu Durumu

- DNS: `api.elyan.dev -> 84.247.172.213`
- HTTPS: aktif
- Reverse proxy: aktif
- Node service: aktif
- Production app path: `/srv/elyan/current`
- Release path: `/srv/elyan/releases/1.0.0-20260421.2`
- Environment file: `/srv/elyan/.env`
- Storage: `/srv/elyan/storage`
- Service name: `elyan`

## `/srv/elyan` Yapısı

Canlı makinede Elyan'a ait yollar şunlar:

- `/srv/elyan/current`
- `/srv/elyan/releases/<version>`
- `/srv/elyan/.env`
- `/srv/elyan/storage`
- `/srv/elyan/.release-current`
- `/srv/elyan/.release-previous`

Mevcut durumda:

- `/srv/elyan/current` symlink'i aktif release'e bakıyor
- systemd servis `elyan.service` bu path'i kullanıyor
- nginx yalnızca `api.elyan.dev` vhost'una yönlendiriyor

## systemd

Servis adı:

- `elyan`

Servis davranışı:

- `Restart=always`
- `WorkingDirectory=/srv/elyan/current`
- `EnvironmentFile=/srv/elyan/.env`
- `ExecStart=/usr/bin/node /srv/elyan/current/.next/standalone/server.js`
- process `127.0.0.1:3010` üzerinde dinliyor

Operasyonel anlamı:

- systemd düşerse servis tekrar kalkar
- deploy sırasında yeni release build edilip symlink güncellenir
- HTTP trafiği doğrudan Node'a değil nginx reverse proxy'ye gelir

## nginx ve SSL

`api.elyan.dev` için ayrı vhost kullanılıyor.

Davranış:

- dışarıdan: `https://api.elyan.dev`
- içeride: `http://127.0.0.1:3010`
- HTTP -> HTTPS yönlendirmesi açık
- Let’s Encrypt sertifikası aktif
- unrelated vhost'lara dokunulmadı

Proxy düzeyi:

- `Host`
- `X-Forwarded-For`
- `X-Forwarded-Proto`
- websocket destekli upgrade header'ları

## `/srv/elyan/.env`

Dosya mevcut ve dolu. Secrets bu dokümana kopyalanmamalı.

Burada set edilen ana değişkenler:

- `DATABASE_URL`
- `NEXTAUTH_URL=https://api.elyan.dev`
- `NEXTAUTH_SECRET`
- `IYZICO_ENV=sandbox`
- `IYZICO_SANDBOX_API_KEY`
- `IYZICO_SANDBOX_SECRET_KEY`
- `IYZICO_SANDBOX_MERCHANT_ID=3425661`
- `IYZICO_SANDBOX_API_BASE_URL=https://sandbox-api.iyzipay.com`
- `GITHUB_OWNER=emrek0ca`
- `GITHUB_REPO=elyan`
- `GITHUB_TOKEN` varsa kullanılacak şekilde tanımlı
- `PORT=3010`
- `HOSTNAME=127.0.0.1`
- `ELYAN_BASE_URL=http://127.0.0.1:3010`
- local runtime için `OLLAMA_URL`, `SEARXNG_URL`, storage path değişkenleri

Not:

- bu dosyada gerçek secret değerleri saklanır
- repo dokümanına secret değer yazmak doğru değil

## PostgreSQL Truth

Production truth yalnızca PostgreSQL'dir.

Canlı DB:

- database adı: `elyan`
- role: `elyan`
- role login: `true`
- role superuser: `false`
- role createdb: `false`
- role createrole: `false`

Kural:

- production file fallback yok
- `DATABASE_URL` yoksa hosted control-plane fail closed davranır
- migration tamamlanmadan production boot ilerlemez

### Migrations

DB bootstrap iki aşamalıdır:

1. `schema_migrations` kontrol edilir
2. eksik migration varsa boot durur

Migration versionları:

- `1` - initial schema
- `2` - evaluation_signals

Bu migration şu tabloları oluşturur:

#### Auth.js canonical tabloları

- `users`
- `accounts`
- `sessions`
- `verification_token`

#### Elyan control-plane tabloları

- `elyan_accounts`
- `elyan_subscriptions`
- `elyan_users`
- `elyan_ledger_entries`
- `elyan_billing_plan_bindings`
- `elyan_status_events`
- `elyan_evaluation_signals`
- `elyan_notifications`
- `elyan_device_links`
- `elyan_devices`

#### Migration gate

- `schema_migrations`

## DB Şeması

### Auth.js tarafı

Bu tablolar NextAuth/Auth.js PostgreSQL adapter path'i içindir:

- `users`
  - `id`
  - `name`
  - `email`
  - `emailVerified`
  - `image`
- `accounts`
  - provider account binding
- `sessions`
  - auth session storage
- `verification_token`
  - email/token doğrulama

Bu katman hosted identity ve session truth'unun canonical kaynağıdır.

### Elyan account/control-plane tarafı

#### `elyan_accounts`

Account ana kaydı:

- `account_id`
- `owner_user_id`
- `display_name`
- `owner_type`
- `billing_customer_ref`
- `status`
- `balance_credits`
- `usage_totals`
- `created_at`
- `updated_at`

#### `elyan_subscriptions`

Subscription truth:

- `account_id`
- `plan_id`
- `status`
- `provider`
- `provider_customer_ref`
- `provider_product_ref`
- `provider_pricing_plan_ref`
- `provider_subscription_ref`
- `provider_status`
- `sync_state`
- `retry_count`
- `last_synced_at`
- `next_retry_at`
- `last_sync_error`
- `current_period_started_at`
- `current_period_ends_at`
- `credits_granted_this_period`

#### `elyan_users`

Hosted identity ile Elyan account ilişkisinin genişletilmiş modeli:

- `user_id`
- `account_id`
- `email`
- `display_name`
- `owner_type`
- `role`
- `password_salt`
- `password_hash`
- `status`
- `created_at`
- `updated_at`
- `last_login_at`

#### `elyan_ledger_entries`

Credit/token muhasebe defteri:

- `entry_id`
- `account_id`
- `kind`
- `status`
- `domain`
- `credits_delta`
- `balance_after`
- `source`
- `request_id`
- `note`
- `created_at`

#### `elyan_billing_plan_bindings`

Iyzico plan binding cache:

- `provider`
- `plan_id`
- `product_name`
- `product_reference_code`
- `pricing_plan_name`
- `pricing_plan_reference_code`
- `currency_code`
- `payment_interval`
- `payment_interval_count`
- `plan_payment_type`
- `sync_state`
- `last_synced_at`
- `last_sync_error`

#### `elyan_status_events`

State transition audit trail:

- `event_id`
- `account_id`
- `event_type`
- `previous_state`
- `next_state`
- `note`
- `created_at`

#### `elyan_evaluation_signals`

Hosted improvement signals:

- `signal_id`
- `account_id`
- `request_id`
- `payload`
- `created_at`

#### `elyan_notifications`

Hesap düzeyi bildirimler:

- `notification_id`
- `account_id`
- `title`
- `body`
- `kind`
- `level`
- `seen_at`
- `created_at`

#### `elyan_device_links`

One-time device link flow:

- `link_code`
- `account_id`
- `user_id`
- `device_label`
- `status`
- `expires_at`
- `created_at`
- `completed_at`
- `consumed_at`
- `device_token`

#### `elyan_devices`

Long-lived device truth:

- `device_id`
- `account_id`
- `user_id`
- `device_label`
- `status`
- `device_token`
- `metadata`
- `last_seen_release_tag`
- `last_seen_at`
- `linked_at`
- `revoked_at`
- `created_at`
- `updated_at`

## Data Model Kuralları

- `users/accounts/sessions/verification_token` Auth.js canonical yoludur
- `elyan_*` tabloları Elyan control-plane truth'udur
- private local context DB'ye yazılmaz
- device sync sadece shared truth taşır
- manual panel edit, gerçek provider truth olmadan paid state üretmez

## Uygulama Akışı

### 1) Auth / Session

Akış:

1. kullanıcı `api.elyan.dev` üzerinden login olur
2. credentials provider identity'yi Elyan control-plane service üzerinden doğrular
3. Auth.js PostgreSQL adapter session truth'unu `sessions` tablosuna bağlar
4. session cookie HTTPS üzerinde `Secure` ve `SameSite=None` olarak taşınır
5. hosted request'ler `requireControlPlaneSession` ile korunur

Sonuç:

- hosted surface auth state için memory kullanmaz
- session truth DB-backed ve canonical'dir

### 2) Account / Subscription

Akış:

1. identity kaydı açılır
2. `elyan_accounts` ve `elyan_users` kaydı oluşur
3. subscription default olarak plan truth ile başlar
4. hosted plan ise provider `manual` ve `sync_state=pending` olur
5. Iyzico bağlanınca provider refs güncellenir

Subscription durumları:

- `trialing`
- `active`
- `past_due`
- `suspended`
- `canceled`

Entitlement kuralı:

- hosted access ancak provider truth `iyzico`, sync `synced`, status `active` veya `trialing` ise açılır

### 3) Billing / Iyzico

Billing truth iki parçadır:

- plan binding
- subscription activation

#### Plan binding algoritması

`ensurePlanBinding()` şu sırayla çalışır:

1. aynı plan için canlı binding varsa kontrol eder
2. varsa cached `productReferenceCode` / `pricingPlanReferenceCode` kullanır
3. yoksa önce provider list endpoint'leri ile mevcut truth'u arar
4. yine yoksa provider create çağrısı yapar
5. provider referans döndürmezse fail eder
6. bağlama truth'unu DB'ye yazar

#### Subscription initialization algoritması

`ensureIyzicoBillingBinding()`:

1. account'ı yükler
2. hosted plan olup olmadığını kontrol eder
3. Iyzico credentials var mı bakar
4. owner identity bağlı mı bakar
5. plan binding'i çözer
6. owner adını parçalar
7. checkout form initialize çağrısı yapar
8. account subscription'ını `provider=iyzico`, `syncState=pending`, `status=trialing` olarak işaretler
9. notification yazar
10. state'i PostgreSQL'e commit eder

#### Webhook algoritması

`applyIyzicoWebhook()`:

1. signature doğrular
2. payload ile account bulur
3. event `subscription.order.success` ise:
   - subscription `active` olur
   - `sync_state=synced`
   - gerekiyorsa credit grant ledger girilir
   - billing notice yazılır
4. event `subscription.order.failure` ise:
   - `retry_count` artar
   - status `past_due` veya `suspended` olur
   - `next_retry_at` hesaplanır
   - entitlement kapatılır
   - warning/error notification yazılır

#### Mevcut gerçek durum

Sandbox merchant hesabında subscription add-on/provisioning aktif olmadığı için Iyzico subscription API create/list çağrıları `422 / Sistem hatası` döndürüyor.

Bu yüzden:

- auth çalışıyor
- billing endpoint dürüst fail ediyor
- fake success yok
- host edilmiş entitlement gerçek provider truth olmadan açılmıyor

### 4) Credits / Ledger

Credit sistemi:

- plan başına aylık included credits vardır
- usage ledger domain bazlıdır
- rate card domain'lere göre çalışır:
  - `inference`
  - `retrieval`
  - `integrations`
  - `evaluation`

Algoritma:

1. account'ın current plan'ı okunur
2. domain rate card değeri alınır
3. units ile çarpılır
4. toplam kredi düşülür
5. bakiye negatif olursa kullanım reddedilir
6. başarılı ise ledger entry yazılır

Ledger entry tipleri:

- `subscription_grant`
- `usage_charge`
- `usage_denial`
- `adjustment`

### 5) Device Sync

Device sync flow local-private context taşımaz.

#### Link start

1. web session ile kullanıcı device link başlatır
2. `link_code` oluşturulur
3. `elyan_device_links`'e pending kayıt yazılır

#### Link complete

1. desktop/client link code'u kullanır
2. device token üretilir
3. `elyan_devices` kaydı açılır
4. link kaydı consumed olur

#### Bootstrap

Device bootstrap yalnızca shared truth döner:

- account
- plan
- entitlements
- ledger / usage summary
- release metadata
- device metadata

Private local veri dönmez.

#### Push

Device heartbeat ve metadata günceller:

- `last_seen_at`
- `last_seen_release_tag`
- `metadata`

#### Unlink

Device access revoke edilir:

- status `revoked`
- token geçersizleşir
- bootstrap artık çalışmaz

### 6) Release / Download

Canonical release source:

- GitHub Releases

Resolver davranışı:

1. repository slug okunur
2. GitHub API releases listelenir
3. draft/prerelease olmayan release aranır
4. aşağıdaki asset'lerin tamamı aranır:
   - `elyan-macos-arm64.zip`
   - `elyan-macos-x64.zip`
   - `elyan-linux-x64.tar.gz`
   - `elyan-windows-x64.zip`
5. tam set yoksa `latest: null`
6. tam set varsa release snapshot döner

Source archive ürün download'u gibi sunulmaz.

`/api/releases/latest` response'u ayrıca şu update alanlarını taşır:

- `currentVersion`
- `currentTagName`
- `updateAvailable`
- `updateStatus`
- `updateMessage`

## Hosted API Yüzeyleri

Canlı endpoint'ler:

- `/api/healthz`
- `/api/control-plane/health`
- `/api/auth/session`
- `/api/control-plane/auth/me`
- `/api/control-plane/auth/register`
- `/api/control-plane/billing/iyzico/initialize`
- `/api/control-plane/billing/iyzico/webhook`
- `/api/releases/latest`
- `/api/control-plane/devices/link/start`
- `/api/control-plane/devices/link/complete`
- `/api/control-plane/devices/sync/bootstrap`
- `/api/control-plane/devices/sync/push`
- `/api/control-plane/devices/unlink`

## Health Özeti

Son doğrulama durumuna göre:

- `/api/healthz` hazır
- `/api/control-plane/health` hazır
- auth/session çalışıyor
- hosted auth configured: `true`
- hosted billing configured: `true`
- `api/releases/latest` çalışıyor fakat publishable release yok
- update status CLI ve panel tarafından açıkça gösteriliyor
- device endpoint'leri auth/token olmadan 401 dönüyor

## Mevcut Canlı Veriler

Son health snapshot'ta görünen durum:

- `accountCount: 4`
- `userCount: 4`
- `deviceCount: 0`
- `deviceLinkCount: 0`
- `ledgerEntryCount: 0`

Bu sayıların zamana göre değişmesi normaldir.

## Algoritmik Karar Kuralları

### Doğruluk önceliği

1. provider truth
2. PostgreSQL truth
3. session truth
4. release truth
5. local defaults

### Fail-closed kurallar

- DATABASE_URL yoksa hosted control-plane çalışmaz
- migration eksikse boot çalışmaz
- auth secret yoksa hosted auth çalışmaz
- Iyzico credential yoksa billing init çalışmaz
- provider error fake success'a çevrilmez

### Silent fallback yasağı

Şunlar sessizce fallback olmaz:

- hosted billing
- session persistence
- release assets
- device token truth

## Yapılmayanlar

Bu VPS düzeni şunları yapmaz:

- private local memory saklamaz
- local dosyaları sync etmez
- unrelated DB'lere dokunmaz
- unrelated nginx vhost'ları değiştirmez
- fake paid state üretmez

## Şu Anda Gerçek Blokaj

Iyzico sandbox merchant hesabı subscription API için provision edilmemiş görünüyor.

Belirti:

- subscription product/list/create çağrıları `422`
- hata kodu `100001`
- hata mesajı `Sistem hatası`

Sonuç:

- code path hazır
- auth hazır
- reverse proxy ve HTTPS hazır
- DB hazır
- fakat gerçek hosted billing activation Iyzico sandbox tarafında blokajlı

## Kısa Operasyon Notu

Eğer ileride billing akışını tekrar deneyeceksen:

1. `api.elyan.dev` auth/session çalışıyor mu kontrol et
2. `POST /api/control-plane/billing/iyzico/initialize` dene
3. Iyzico tarafında subscription add-on / sandbox provisioning doğrula
4. webhook ile `subscription.order.success` gelirse entitlement açılır

## Sonuç

Bugünkü gerçek durum:

- VPS canlı
- PostgreSQL canlı
- hosted auth canlı
- hosted release resolver canlı
- device sync yüzeyleri canlı
- Iyzico sandbox provider tarafı kısmi/kapalı

Bu yüzden sistem artık sahte başarı göstermiyor; gerçek truth neyse onu dönüyor.
