 Elyan VPS / Deploy / Control-Plane Reality

Bu dosya Elyan'ın VPS üzerindeki gerçek durumunu unutmamak ve geliştirme sırasında yanlış mimari kararları önlemek için yazıldı.

Yeni sistem uydurulmayacak. Mevcut yapı source of truth kabul edilerek geliştirilecek.

---

## 1. Sunucu ve deploy özeti

- Deploy root: `/srv/elyan`

- Current symlink: `/srv/elyan/current`

- Current release target: `/srv/elyan/releases/1.0.0-20260421.2`

- Previous release marker: `/srv/elyan/releases/1.0.0-20260421.1`

- Elyan env file: `/srv/elyan/.env`

- Elyan systemd service name: `elyan`

- App process localhost binding: `127.0.0.1:3010`

- Public hosted API domain: `https://api.elyan.dev`

Servis systemd ile çalışıyor ve deploy mantığı symlink tabanlı.

---

## 2. systemd / çalışma şekli

Elyan service:

- service name: `elyan`

- runtime: Next.js standalone server

- process user: `elyan`

- process group: `elyan`

- working directory: `/srv/elyan/current`

- env file: `/srv/elyan/.env`

- service port: `127.0.0.1:3010`

Ürün zaten systemd + nginx reverse proxy ile canlıda çalışıyor.

Yeni deploy sistemi icat edilmemeli.

---

## 3. Nginx / domain gerçekleri

- Public API domain: `api.elyan.dev`

- Nginx reverse proxy app’i `127.0.0.1:3010` adresine yönlendiriyor

- TLS / HTTPS aktif

- Nginx config zaten var, yeni frontend/backend mimarisi kurarken bu gerçek korunmalı

Not:

- Nginx tarafında VPS üzerinde başka projeler de var

- Elyan geliştirilirken diğer domain / conf dosyaları bozulmamalı

---

## 4. Environment variable gerçekleri

Sanitized env keys:

- `DATABASE_URL`

- `ELYAN_BASE_URL`

- `ELYAN_CONTROL_PLANE_STATE_PATH`

- `ELYAN_DEPLOY_ROOT`

- `ELYAN_ENV_FILE`

- `ELYAN_RUNTIME_SETTINGS_PATH`

- `ELYAN_STORAGE_DIR`

- `GITHUB_OWNER`

- `GITHUB_REPO`

- `GITHUB_TOKEN`

- `GROQ_API_KEY`

- `HOSTNAME`

- `IYZICO_API_KEY`

- `IYZICO_ENV`

- `IYZICO_MERCHANT_ID`

- `IYZICO_SANDBOX_API_BASE_URL`

- `IYZICO_SANDBOX_API_KEY`

- `IYZICO_SANDBOX_MERCHANT_ID`

- `IYZICO_SANDBOX_SECRET_KEY`

- `IYZICO_SECRET_KEY`

- `NEXTAUTH_SECRET`

- `NEXTAUTH_URL`

- `OLLAMA_URL`

- `PORT`

- `SEARXNG_URL`

Önemli:

- `GROQ_API_KEY` mevcut

- `NEXTAUTH_URL` mevcut

- `DATABASE_URL` mevcut

- `IYZICO_*` değişkenleri mevcut

- `OLLAMA_URL` mevcut

- `SEARXNG_URL` mevcut

Yani auth, providers, billing, model registry ve search için temel env yüzeyi zaten var.

---

## 5. Kod yapısı gerçeği

### App routes

Temel yüzeyler mevcut:

- `/`

- `/auth`

- `/panel`

- `/panel/account`

- `/panel/billing`

- `/panel/notifications`

- `/panel/usage`

- `/docs`

- `/download`

- `/pricing`

- `/platform`

- `/manage`

- `/chat/[id]`

- `/chat/new`

### API routes

Aşağıdaki hosted/control-plane ve runtime yüzeyleri zaten mevcut:

- `/api/auth/[...nextauth]`

- `/api/chat`

- `/api/me`

- `/api/models`

- `/api/healthz`

- `/api/releases/latest`

- `/api/runtime/config`

- `/api/capabilities`

- `/api/preview/chat`

### Control-plane routes

Mevcut route’lar:

- `/api/control-plane/auth/me`

- `/api/control-plane/auth/register`

- `/api/control-plane/plans`

- `/api/control-plane/panel`

- `/api/control-plane/accounts/[accountId]`

- `/api/control-plane/accounts/[accountId]/usage`

- `/api/control-plane/interactions/context`

- `/api/control-plane/interactions/drafts/[draftId]/promote`

- `/api/control-plane/notifications/[notificationId]`

- `/api/control-plane/devices/link/start`

- `/api/control-plane/devices/link/complete`

- `/api/control-plane/devices/sync/bootstrap`

- `/api/control-plane/devices/sync/push`

- `/api/control-plane/devices/unlink`

- `/api/control-plane/devices/rotate`

- `/api/control-plane/health`

- `/api/control-plane/billing/iyzico/initialize`

- `/api/control-plane/billing/iyzico/webhook`

### Channel routes

Mevcut channel yüzeyleri:

- telegram

- whatsapp

- imessage / bluebubbles

### Core modules

Aşağıdaki omurga zaten var:

- `src/core/control-plane/*`

- `src/core/orchestration/*`

- `src/core/agents/*`

- `src/core/providers/*`

- `src/core/search/*`

- `src/core/capabilities/*`

- `src/core/channels/*`

- `src/core/mcp/*`

- `src/core/runtime-settings/*`

- `src/core/runtime-config/*`

Yeni paralel mimari kurma.

Bu omurga genişletilecek.

---

## 6. Sağlık / runtime gerçekleri

`/api/healthz` sonucuna göre:

- service hazır

- production modda

- runtime `local-first`

- search opsiyonel ve şu an offline olabilir

- model count: 10

- local Ollama modelleri mevcut

- cloud Groq modelleri mevcut

- hosted auth configured: true

- hosted billing configured: true

### Modeller

Local:

- `ollama:deepseek-r1:8b`

- `ollama:llama3:8b`

- `ollama:llama3:latest`

- `ollama:qwen2.5-coder:3b`

- `ollama:qwen2.5:7b-instruct-q5_K_M`

Cloud:

- `groq:gemma2-9b-it`

- `groq:llama-3.1-70b-versatile`

- `groq:llama-3.1-8b-instant`

- `groq:llama-3.3-70b-versatile`

- `groq:mixtral-8x7b-32768`

Önemli sonuç:

- Elyan şu an hibrit provider mantığına zaten sahip

- local + cloud provider routing zemini var

- Groq entegrasyonu env ve provider registry seviyesinde mevcut

---

## 7. Releases gerçekleri

`/api/releases/latest` çalışıyor.

Mevcut repo:

- `emrek0ca/elyan`

Son görülen release:

- `v1.1.0`

Required assets:

- `elyan-macos-arm64.zip`

- `elyan-macos-x64.zip`

- `elyan-linux-x64.tar.gz`

- `elyan-windows-x64.zip`

Release surface zaten canlı.

---

## 8. Auth gerçeği

Mevcut auth stack:

- NextAuth credentials flow var

- `/api/auth/[...nextauth]` aktif

- `/api/me` session varsa çalışıyor

- session yoksa `/api/me` doğru şekilde `401` dönüyor

- `NEXTAUTH_SECRET` ve `NEXTAUTH_URL` mevcut

- PostgreSQL tabanlı auth/session tabloları var

Not:

- Hosted auth çalışıyor

- `api/me` artık gerçek session truth yüzeyi

Yeni auth sistemi kurma.

Var olan auth geliştirilecek.

---

## 9. Preview chat gerçeği

Ayrı yüzey:

- `/api/preview/chat`

Bu endpoint:

- website’deki “Elyan ile tanış” yüzeyi için

- ana `/api/chat` akışından ayrı

- bot/runtime/chat reposuyla karıştırılmamalı

- frontend doğrudan provider’a gitmeyecek, bu endpoint’i tüketecek

Bu yüzey ürünün ilk izlenim / preview chat alanı olarak kalmalı.

---

## 10. Billing / iyzico gerçeği

Billing route’ları mevcut:

- `/api/control-plane/billing/iyzico/initialize`

- `/api/control-plane/billing/iyzico/webhook`

Plan binding ve subscription modeli control-plane içinde mevcut.

Ama kritik gerçek:

- iyzico sandbox merchant subscription yetkisi eksik olabilir

- bu frontend bug değildir

- fake active billing / fake subscription state üretme

- sandbox / unavailable / coming soon fallback dürüst şekilde gösterilmeli

Yani billing altyapısı var, ama merchant provisioning dış bağımlılık.

---

## 11. Veritabanı gerçeği

Database:

- PostgreSQL 16

- db name: `elyan`

### Şemalar

- `public`

### Auth / NextAuth tabloları

- `public.accounts`

- `public.sessions`

- `public.users`

- `public.verification_token`

### Elyan control-plane tabloları

- `public.elyan_accounts`

- `public.elyan_billing_plan_bindings`

- `public.elyan_device_links`

- `public.elyan_devices`

- `public.elyan_ledger_entries`

- `public.elyan_notifications`

- `public.elyan_status_events`

- `public.elyan_subscriptions`

- `public.elyan_users`

- `public.schema_migrations`

Yani control-plane için ayrı tablo kümesi zaten var.

---

## 12. DB domain modeli (mevcut)

### `elyan_users`

- hosted control-plane user kimliği

- email

- display name

- owner_type

- role

- password_salt

- password_hash

- status

- created / updated / last_login

### `elyan_accounts`

- account_id

- owner_user_id

- display_name

- owner_type

- billing_customer_ref

- status

- balance_credits

- usage_totals (jsonb)

- created_at / updated_at

### `elyan_subscriptions`

- account_id

- plan_id

- status

- provider

- provider refs

- sync_state

- retry_count

- sync timestamps

- current period start/end

- credits granted

### `elyan_billing_plan_bindings`

- provider

- plan_id

- product / pricing plan refs

- sync_state

- sync timestamps

- payment interval metadata

### `elyan_devices`

- device_id

- account_id

- user_id

- device_label

- status

- device_token

- metadata

- last_seen_release_tag

- linked_at / revoked_at

- timestamps

### `elyan_device_links`

- link_code

- account_id

- user_id

- device_label

- status

- expires_at

- completed_at

- consumed_at

- device_token

### `elyan_ledger_entries`

- entry_id

- account_id

- kind

- status

- domain

- credits_delta

- balance_after

- source

- request_id

- note

- created_at

### `elyan_notifications`

- notification_id

- account_id

- title

- body

- kind

- level

- seen_at

- created_at

### `elyan_status_events`

- state transition / audit benzeri kayıt

Sonuç:

- account

- subscription

- device linking

- usage accounting

- notifications

- billing plan binding

zemini zaten kurulmuş.

---

## 13. Row count snapshot

Audit anındaki yaklaşık row counts:

- `elyan_accounts`: 9

- `elyan_billing_plan_bindings`: 4

- `elyan_notifications`: 9

- `elyan_status_events`: 10

- `elyan_subscriptions`: 9

- `elyan_users`: 9

- `schema_migrations`: 1

Şu an boş veya henüz aktif kullanılmayanlar:

- `elyan_device_links`

- `elyan_devices`

- `elyan_ledger_entries`

- `sessions`

- `users`

- `accounts`

- `verification_token`

Bu da şunu gösteriyor:

- control-plane user/account/subscription mantığı kullanılıyor

- NextAuth’ın klasik `users/sessions/accounts` tabloları henüz az kullanılmış veya farklı akışla çalışıyor olabilir

- device ve usage enforcement henüz erken aşamada

- interaction context ve learning draft promotion, hosted memory yüzeyinin parçaları olarak uygulanıyor

- device rotate, device token yenileme ve revoke akışını tamamlıyor

---

## 14. Plan sistemi gerçeği

`/api/control-plane/plans` çalışıyor ve şu planlar mevcut:

- `local_byok`

- `cloud_assisted`

- `pro_builder`

- `team_business`

Plan fields:

- title

- summary

- monthlyPriceTRY

- monthlyIncludedCredits

- entitlements

- rateCard

- rateLimits

- upgradeTriggers

- pricing narrative

Entitlement mantığı zaten var:

- hostedAccess

- hostedUsageAccounting

- managedCredits

- cloudRouting

- advancedRouting

- teamGovernance

- hostedImprovementSignals

Yani plan/entitlement sistemi sıfırdan yazılmayacak.

Genişletilecek ve enforce edilecek.

---

## 15. Mevcut ürün yönü

Elyan şu an zaten şunların temeline sahip:

- local-first runtime

- hosted control-plane

- hybrid model providers

- search layer

- orchestration layer

- capabilities/tools

- channel adapters

- plan + billing + entitlement zemini

- release distribution surface

Bu yüzden bundan sonra yapılacak işler:

- yeni ürün icat etmek değil

- mevcut omurgayı sıkılaştırmak

- auth / panel / subscription / usage / device / gating tarafını ürün kalitesine taşımak

- web / desktop / CLI / channels yüzeylerini tek account truth’una bağlamak

---

## 16. Değiştirilmemesi gereken prensipler

- Yeni paralel auth sistemi kurma

- Yeni paralel billing sistemi kurma

- Yeni paralel account truth oluşturma

- Mevcut VPS gerçeklerini yok sayma

- `api.elyan.dev` yüzeyini bozma

- `/srv/elyan/current` deploy mantığını bozma

- Preview chat’i ana runtime chat ile karıştırma

- iyzico sandbox kısıtını frontend bug gibi ele alma

- Fake subscription state üretme

- Fake hosted active state üretme

---

## 17. Bundan sonra geliştirilecek ana alanlar

1. Auth zorunluluğu / hesap olmadan kullanım yok

2. Device linking ve desktop / CLI account bağlama

3. Daily usage counters

4. Usage ledger enforcement

5. Plan bazlı hosted access gating

6. Upgrade CTA / panel truth

7. Web + CLI + desktop aynı account truth’una bağlanması

8. Speed mode + research mode + memory/project ayrımının güçlenmesi

9. Learning draft -> promote akışının büyütülmesi

---

## 18. Geliştirme talimatı

Bu dosyayı okuyan agent / Codex / geliştirici:

- önce mevcut kodu ve bu VPS gerçeklerini okuyacak

- sonra mevcut omurgayı geliştirerek ilerleyecek

- sıfırdan mimari kurmayacak

- var olan control-plane, auth, subscriptions, devices, plans, billing ve orchestration katmanını genişletecek

- çalışan parçaları kırmayacak

- her değişiklikte source of truth olarak bu dosyayı ve gerçek kodu baz alacak
