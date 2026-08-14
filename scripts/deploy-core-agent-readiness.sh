#!/usr/bin/env bash
set -euo pipefail

REMOTE_HOST="${REMOTE_HOST:-root@84.247.172.213}"
REMOTE_DIR="${REMOTE_DIR:-/srv/elyan-backend}"
COMPOSE_FILE="${COMPOSE_FILE:-compose.server.yaml}"
STAMP="${STAMP:-$(date -u +%Y%m%dT%H%M%SZ)}"
BACKUP_DIR="${REMOTE_DIR}/.codex-backups/${STAMP}-quantum-neural-readiness"

echo "==> Local backend tests"
npm test -- health runtime tasks chat brain auth realtime routing-policy

echo "==> Remote backup: ${BACKUP_DIR}"
ssh "${REMOTE_HOST}" "mkdir -p '${BACKUP_DIR}' && cd '${REMOTE_DIR}' && cp -a package.json package-lock.json ${COMPOSE_FILE} src scripts '${BACKUP_DIR}/' && if [ -d ml-worker ]; then cp -a ml-worker '${BACKUP_DIR}/'; fi"

echo "==> Sync exact backend files"
# `bin/` DERLENMİŞ ÇIKTIDIR, kaynak değil. Geliştirici Mac'inde üretilen
# `bin/elyan_nlp` bir Mach-O arm64 ikilisidir; Linux sunucuya kopyalanınca
# hiç çalışamaz ve C hızlandırılmış NLP yolu sessizce ölür (23 Tem–7 Ağu
# arası prod tam olarak bu durumdaydı: her istek yavaş JS yoluna düşüyordu).
# Sunucuda kaynaktan derliyoruz.
# `secrets/` YALNIZ SUNUCUDA yaşar (Apple IAP ve APNS özel anahtarları; repoda
# yokturlar ve olmamalıdırlar). Hariç tutulmadığı için `--delete` onları
# siliyordu; ardından compose'un bind-mount'ları yerlerine BOŞ KLASÖR yaratıyor
# ve hata vermeden Apple abonelik doğrulaması ile push bildirimleri ölüyordu.
# `.blob-store/` de aynı sebeple korunur: çalışma zamanı verisi.
rsync -az --delete \
  --exclude node_modules \
  --exclude dist \
  --exclude bin \
  --exclude .git \
  --exclude .env \
  --exclude secrets \
  --exclude .blob-store \
  --exclude .codex-backups \
  --exclude .codex-worktrees \
  ./ "${REMOTE_HOST}:${REMOTE_DIR}/"

echo "==> Compile native NLP on the target architecture"
ssh "${REMOTE_HOST}" "cd '${REMOTE_DIR}' && npm run compile:nlp"

echo "==> Remote tests"
ssh "${REMOTE_HOST}" "cd '${REMOTE_DIR}' && npm ci && npm test -- health runtime tasks chat brain auth realtime routing-policy"

echo "==> Schema bootstrap and Docker restart"
# chat-worker / brain-worker / document-worker DERLENMİŞ İMAJ çalıştırıyor
# (`node dist/workers/*.js`), volume mount değil. Listede olmadıkları için
# deploy sonrası ESKİ imajda kalıyorlardı: backend yenilenmiş görünürken
# sohbet üretimi hâlâ eski kodu koşuyordu — "düzelttim ama değişmedi"
# vakalarının kaynağı buydu.
ssh "${REMOTE_HOST}" "cd '${REMOTE_DIR}' && bash scripts/bootstrap-v1-social-auth-schema.sh && bash scripts/bootstrap-v4-identity-quota-schema.sh && docker compose -f '${COMPOSE_FILE}' up -d --build redis backend training-worker ml-worker chat-worker brain-worker document-worker"

echo "==> Health poll"
HEALTH_OK=0
for attempt in {1..30}; do
  # Kapı, `/healthz`'in GERÇEKTEN yayınladığı alanlara bakar. Eskiden
  # `agent.chatReady` gibi iç gözlem alanları aranıyordu; `shapePublicHealthPayload`
  # (src/modules/health/routes.ts) bunları 24 Haziran'dan beri dışarı vermiyor,
  # yani kapı hiçbir koşulda geçemiyordu: her deploy "Health failed" diyor,
  # benchmark adımı hiç çalışmıyor ve gerçek bir arıza ile bu sahte düşüş
  # ayırt edilemiyordu. `/healthz` sağlıksızken zaten 503 döner ve `curl -fsS`
  # orada düşer; buradaki kontrol onun üstüne anlamlı alanları doğrular.
  if curl -fsS https://api.elyan.dev/healthz | node -e "let d='';process.stdin.on('data',c=>d+=c);process.stdin.on('end',()=>{try{const j=JSON.parse(d);const surfaces=Array.isArray(j.coreSurfaces)?j.coreSurfaces:[];const required=['chat','brain','tasks','runtime','realtime','auth'];const ok=j.ok===true&&j.status==='ok'&&j.mobile?.statusSummary==='ready'&&j.mobile?.safeForExternalClients===true&&j.realtime?.sseEnabled===true&&j.network?.externalClientsCanReachAdvertisedBaseUrl===true&&required.every((s)=>surfaces.includes(s));if(ok)process.exit(0);console.error('health gate mismatch: '+JSON.stringify({ok:j.ok,status:j.status,mobile:j.mobile,sse:j.realtime?.sseEnabled,reachable:j.network?.externalClientsCanReachAdvertisedBaseUrl,missing:required.filter((s)=>!surfaces.includes(s))}));process.exit(1);}catch(e){console.error('health payload unreadable: '+e.message);process.exit(1);}})"; then
    echo "Health OK"
    HEALTH_OK=1
    break
  fi
  sleep 3
done

if [ "${HEALTH_OK}" -eq 1 ]; then
  echo "==> Reasoning benchmark (warn-only)"
  # `|| echo` ŞART: bu adım "warn-only" etiketli ama `set -e` altında ölümcüldü.
  # npm çıktısı JSON'un ARDINDAN da satır yazıyor, ilk `{`'ten sonuna kadar
  # dilimlemek `Unexpected non-whitespace character after JSON` ile patlıyordu;
  # sağlık geçmiş deploy'lar exit 1 dönüyor, yani çıkış kodu YALAN söylüyordu.
  # Gerçek bir arıza ile bu gürültü ayırt edilemez hâle geliyordu.
  # `runner_error` MUTLAKA basılır: benchmark CLI her hatayı jenerik
  # `status:warn, case_count:0` yüküne çeviriyor. O alan basılmayınca
  # "ölçüm koştu ama 0 vaka" ile "ölçüm hiç başlamadı" ayırt edilemiyordu —
  # canlıda sebep `RUNTIME_SECRET_PEPPER: Required` idi ve haftalarca görünmedi.
  # Ölçüm KONTEYNER İÇİNDE koşar. Host'ta koşarken veritabanına hiç
  # ulaşamıyordu: DATABASE_URL compose servis adını (`postgres`) gösteriyor
  # ve o ad yalnız docker ağının içinde çözülür. `runner_error` görünür
  # olunca ortaya çıktı (2026-08-14): "Failed query: select id, role from users".
  ssh "${REMOTE_HOST}" "cd '${REMOTE_DIR}' && if docker compose -f compose.server.yaml exec -T backend node dist/modules/brain/benchmark-cli.js > .codex-benchmark.json 2>&1; then node -e \"const fs=require('fs');const raw=fs.readFileSync('.codex-benchmark.json','utf8');const b=raw.indexOf('<<<ELYAN_BENCHMARK_RESULT');const e=raw.indexOf('ELYAN_BENCHMARK_RESULT>>>');const body=(b>=0&&e>b)?raw.slice(b+25,e):raw;const start=body.indexOf('{');const end=body.lastIndexOf('}');if(start<0||end<start)throw new Error('benchmark output carries no JSON object');const data=JSON.parse(body.slice(start,end+1));console.log(JSON.stringify({status:data.status,overall_score:data.overall_score,boundary_score:data.boundary_score,reasoning_score:data.reasoning_score,clarification_score:data.clarification_score,tool_use_score:data.tool_use_score,latency_score:data.latency_score,case_count:data.case_count,live_model_case_count:data.live_model_case_count,runner_error:data.runner_error ?? null}, null, 2)); if(data.status!=='pass') console.log('BENCHMARK_WARN_ONLY=1');\"; else echo 'Benchmark runner failed; continuing warn-only.'; fi" || echo "Benchmark step failed; deploy already healthy, continuing warn-only."
  echo "==> Deploy complete (health verified)"
  exit 0
fi

echo "Health failed. Rollback command:"
echo "ssh ${REMOTE_HOST} \"cd '${REMOTE_DIR}' && cp -a '${BACKUP_DIR}/package.json' '${BACKUP_DIR}/package-lock.json' '${BACKUP_DIR}/${COMPOSE_FILE}' '${REMOTE_DIR}/' && rm -rf src ml-worker && cp -a '${BACKUP_DIR}/src' src && cp -a '${BACKUP_DIR}/ml-worker' ml-worker && docker compose -f '${COMPOSE_FILE}' up -d --build backend training-worker ml-worker\""
exit 1
