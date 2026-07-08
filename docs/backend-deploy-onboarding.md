# Elyan Backend — Geliştirici Onboarding & Deploy Rehberi

Bu doküman backend'de çalışacak yazılımcı için: repo nerede, yerelde nasıl
çalıştırılır, sunucuya nasıl bağlanılır, deploy nasıl yapılır, sunucuda ne
nerede durur.

## 1. Repo ve yerel konum

- Yerel çalışma kopyası: `/Users/emrekoca/Desktop/elyan-backend`
- Yığın: Node.js + TypeScript, Fastify, PostgreSQL (pgvector/pg16) + Drizzle ORM,
  Redis, SearXNG (web arama), Docker Compose.
- Kaynak: `src/` (modüller `src/modules/...`), derlenmiş çıktı: `dist/`,
  şema/migration: `drizzle/`, operasyon scriptleri: `scripts/`, SQL ops: `ops/sql`.
- Ana dokümanlar: `README.md` (API yüzeyleri, quick start), `AGENTS.md`,
  `docs/` (mobile/desktop handoff, billing, streaming).

## 2. Yerel geliştirme

İki yol var; mobil/desktop geliştiricisiyle aynı makinede çalışıyorsan Compose
önerilir:

**A) Docker Compose (önerilen):**
```bash
cd /Users/emrekoca/Desktop/elyan-backend
cp .env.example .env          # ilk kurulumda
docker compose up --build     # backend + postgres + redis (compose.yaml)
npm run db:push               # şemayı bas
```

**B) Host üzerinde doğrudan:**
```bash
# PostgreSQL 127.0.0.1:5432'de çalışıyor olmalı
npm install
npm run db:push
npm run dev                   # tsx watch src/index.ts
```

Önemli:
- Fiziksel telefon veya başka makine bağlanacaksa `.env` içindeki
  `APP_BASE_URL` LAN IP'si ya da public host olmalı; `127.0.0.1` yalnız aynı
  makinede çalışır. `/healthz` advertise edilen origin'i raporlar — yanlış
  ayar hemen görünür.
- `npm test` önce build alır, sonra `dist/**/*.test.js` dosyalarını koşar.
- `npm run compile:nlp` yerel C yardımcı binary'sini (`bin/elyan_nlp`) derler;
  gcc gerekir (deploy scripti bunu sunucuda da çalıştırır).

## 3. Sunucu

- **VPS**: `84.247.172.213` — SSH kullanıcısı `root`, **port 2222**
  (standart 22 değil; `~/.ssh/config`'te tanımlı).
  ```
  ssh -p 2222 root@84.247.172.213
  ```
  Yeni geliştirici için: public SSH anahtarın sunucudaki
  `~/.ssh/authorized_keys`'e eklenmeli (mevcut erişimi olan biri ekler).
- **Prod dizini**: `/srv/elyan-backend` — repo'nun rsync ile senkronlanan
  kopyası. Git remote'tan pull edilmez; deploy scripti yereldeki working
  tree'yi rsync'ler.
- **Public URL**: `https://api.elyan.dev` (TLS/proxy katmanı backend
  container'ının önünde; backend yalnız `127.0.0.1:4000`'e bind olur —
  proxy'nin ne olduğu (nginx/caddy) sunucuda `systemctl` ile doğrulanabilir).
- **Servisler** (`compose.server.yaml`, hepsi Docker Compose ile):
  `postgres` (pgvector/pg16), `redis` (7-alpine), `searxng`, `backend`
  (port 4000, sadece loopback'e açık), `training-worker`, `brain-worker`,
  `document-worker`, `proactive-scheduler`, `ml-worker`.
- **Secrets**: `.env` sunucuda `/srv/elyan-backend/.env` olarak durur ve
  rsync'te **hariç tutulur** (asla yereldekiyle ezilmez). Apple IAP imza
  anahtarı: `/srv/elyan-backend/secrets/apple-iap-private-key.p8` (dizin 700,
  dosya 600).
- **Yedekler**: her deploy öncesi `/srv/elyan-backend/.codex-backups/<UTC-damga>-v1-release/`
  altına package.json, compose, .env, src, scripts, drizzle, ops, ml-worker
  kopyalanır.

## 4. Deploy

Tek komut — yerel repo kökünden:

```bash
cd /Users/emrekoca/Desktop/elyan-backend
bash scripts/deploy-v1-release.sh
```

Script sırayla şunları yapar (başarısız adımda durur, `set -euo pipefail`):

1. **Yerel kapı**: `npm ci` → `npm run build` → `npm test`. Yerel testler
   geçmeden sunucuya hiçbir şey gitmez.
2. **Uzak yedek**: `/srv/elyan-backend/.codex-backups/<damga>/` oluşturulur.
3. **Rsync**: working tree sunucuya senkronlanır
   (`node_modules`, `dist`, `.git`, `.env*`, `secrets`, `.codex-backups` hariç).
4. **Apple anahtarı** (opsiyonel): `APPLE_PRIVATE_KEY_SOURCE` verildiyse scp
   ile taşınır; yoksa sunucudaki mevcut anahtar doğrulanır.
5. **Uzak derleme**: sunucuda `npm ci && npm run compile:nlp && npm run build && npm test`.
6. **Şema + yeniden başlatma**: `docker compose -f compose.server.yaml up -d postgres redis`
   → `scripts/bootstrap-v1..v10-*.sh` şema bootstrapları →
   `docker compose -f compose.server.yaml up -d --build backend training-worker brain-worker document-worker proactive-scheduler ml-worker`.
7. **Probe**: `scripts/probe-v1-runtime-flow.sh` 6 denemeye kadar
   `https://api.elyan.dev` + `http://84.247.172.213:4000/healthz` üzerinden
   sağlık doğrular.

Değişkenlerle özelleştirme: `REMOTE_HOST`, `REMOTE_DIR`, `COMPOSE_FILE`,
`PUBLIC_BASE_URL` env olarak geçilebilir (varsayılanlar yukarıdaki değerler).

### Rollback

Script çıktısında damgalı yedek yolu yazar. Özet:

```bash
ssh -p 2222 root@84.247.172.213
cd /srv/elyan-backend
# .codex-backups/<damga>-v1-release/ içinden package.json, package-lock.json,
# compose.server.yaml, .env, src, scripts, drizzle, ml-worker geri kopyala
docker compose -f compose.server.yaml up -d --build postgres redis backend training-worker ml-worker
```

## 5. Sunucuda günlük operasyon

```bash
ssh -p 2222 root@84.247.172.213
cd /srv/elyan-backend

docker compose -f compose.server.yaml ps                  # servis durumu
docker compose -f compose.server.yaml logs -f backend     # canlı log
docker compose -f compose.server.yaml restart backend     # tek servisi yeniden başlat
docker compose -f compose.server.yaml up -d --build backend  # imajı yeniden kur
```

Sağlık uçları: `GET /healthz`, `GET /livez`, `GET /readyz` — public olarak
`https://api.elyan.dev/healthz`, doğrudan `http://84.247.172.213:4000/healthz`
(sunucu içinden `curl 127.0.0.1:4000/healthz`).

Her yanıt `x-request-id` döner; log korelasyonu bu id ile yapılır.

## 6. Feature flag / otonomi fazları

`.env` üzerinden yönetilen faz bayrakları için:

```bash
bash scripts/enable-autonomy-phase.sh <faz>
```

Script sunucudaki `.env`'i yedekleyip (`.env.bak-autonomy`) bayrağı yazar ve
`api`/`backend` servisini yeniden başlatır; geri alma yolu script içinde.

## 7. Kurallar / dikkat

- **`.env` ve `secrets/` asla rsync ile ezilmez** — prod sırları yalnız
  sunucuda yaşar. Yeni bir env değişkeni eklediysen sunucudaki `.env`'e elle
  ekle, sonra ilgili servisi yeniden başlat.
- **Şema değişiklikleri** `scripts/bootstrap-v*.sh` zinciriyle idempotent
  uygulanır; deploy scripti hepsini her seferinde koşar.
- Mobil/desktop istemci sınırı: mobil yalnız `POST /v1/chat/messages` ve
  `GET /v1/realtime/stream` kullanır; desktop runtime kanalı
  (`/v1/realtime/runtime` websocket) ve model sağlayıcıları backend'e özeldir.
- Deploy her zaman `deploy-v1-release.sh` ile yapılmalı — elle rsync/restart
  yedek ve probe adımlarını atlar.
