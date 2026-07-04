# Elyan Backend — Agent Reference

Bu repo Elyan'ın backend/control-plane ve server-brain katmanıdır.
Elyan bir chatbot değil; veri okuyan, veri yazan, state yöneten, ölçülen ve zamanla
tool/goal-loop ile iş yürüten bir ajan altyapısıdır.

## Repo Özeti

- Stack: Node.js, TypeScript, Fastify, PostgreSQL + Drizzle, Redis + BullMQ.
- Realtime: SSE event contract korunur.
- AI provider: Groq ve ileride Elyan model provider planı; provider/model adı kullanıcıya sızdırılmaz.
- Mobile/desktop contract: mevcut API shape, SSE event isimleri ve `elyan_blocks.v2` blok şeması bozulmaz.
- Deploy: sadece kullanıcı istediğinde VPS'e deploy edilir.

Temel komutlar:

```bash
npm run build
npm test
npx tsc --noEmit
npm run evaluate:block-output
JWT_SECRET=benchmark-test-secret-32-characters npm run benchmark:security
JWT_SECRET=benchmark-test-secret-32-characters npm run benchmark:routing
```

Standart VPS deploy:

```bash
bash scripts/deploy-v1-release.sh
```

## Mimari İlke

Düz metin sadece kullanıcının gördüğü son yüzeydir. Backend içinde kararlar ve
hafıza düz metinden kazınmaz; mümkün olduğunca tipli JSON, canonical state,
event log, metric ve policy kayıtlarıyla yürür.

Ana akış:

```text
Mobile/Desktop client
  -> Fastify API
  -> routing/admission/security policy
  -> server brain inference
  -> typed blocks + memory/state/goal/tool metadata
  -> PostgreSQL/Redis event state
  -> SSE/REST response
```

Backend private local computer actions çalıştırmaz. Desktop runtime özel dosya,
browser, computer-use ve MCP execution sınırıdır. Backend sadece auth, billing,
routing, orchestration metadata, memory/state, learning events ve realtime truth
yönetir.

## Korunacak Public Contract

Asla breaking change yapma:

- `/v1/chat/messages`
- `/v1/realtime/stream`
- `/v1/tasks`
- `/v1/billing/*`
- SSE events: `message.created`, `message.delta`, `message.completed`, `heartbeat`
- `elyan_blocks.v2`

Yeni alan eklenebilir. Var olan alan silinmez, yeniden adlandırılmaz, anlamı sessizce
değiştirilmez.

Streaming monotoniktir: yayınlanan delta geri alınmaz.

## Son Yapılanlar

### Benchmark ve Telemetri Foundation

- JSONL benchmark loader artık `input` yanında `message` formatını da normalize eder.
- `expectedWorkload` workload benchmark beklentisine çevrilir.
- `block-output-policy.jsonl` ana benchmark özetine uyumlu hale getirildi.
- `turn_metrics` tablosu eklendi.
- `recordTurnMetric` fire-and-forget çalışır; DB hatası kullanıcı cevabını, SSE'i veya billing'i etkilemez.
- Prompt/content/private text turn metrics'e yazılmaz.

### Memory ve Tercih Güncelleme

- Preferred-name gibi tek değerli kullanıcı tercihleri canonical key üzerinden yönetilir.
- En son açık kullanıcı isteği kazanır; eski hitap adları aktif prompt'a karışmaz.
- Explicit memory write yolu güçlendirildi; "bana X diye hitap et" gibi bilgiler bir sonraki turda etkili olacak şekilde yazılır.
- Memory okumada safe, scoped ve dedupe edilmiş paketler tercih edilir.

### Dialogue State Store

- `dialogue_states` tablosu eklendi.
- Server-owned dialogue state modeli eklendi: goal, stage, open loops, user memory, tool history, style and mood signals.
- Client metadata artık kaynak değil, en fazla destekleyici ipucudur.
- Server state metadata'sı `server_dialogue_state.v1` kaynağıyla damgalanır.

### Kullanıcılar Arası Veri İzolasyonu

Kritik düzeltme: Backend artık mobilin gönderdiği untrusted `compactContext`,
`rollingSummary`, `recentMessages` veya `userMemory` alanlarına körü körüne güvenmez.

Yeni kural:

- Dialogue metadata sadece server tarafından `server_dialogue_state.v1` olarak damgalandıysa güvenilir.
- Metadata `userId` ile eşleşmek zorunda.
- Session varsa `sessionId` de eşleşmek zorunda.
- Eşleşmeyen client cache prompt'a, continuity summary'ye veya fallback dialogue state'e girmez.

Bu, hesap değişimi sonrası başka kullanıcının eski mobil cache'inden state sızmasını keser.

### Agent Foundation

- `tool-registry` ve sınırlı `agent-loop` temeli eklendi.
- İlk server-brain tool seti mevcut yetenekleri tool olarak paketler:
  - `web.search`
  - `memory.query`
  - `memory.write`
  - `goals.update`
- Write/side-effect tool'lar policy ile kapalı gelir; state write sadece açıkça izin verilen internal yolda çalışır.
- `session_goals` yanında append-only goal event modeli için foundation eklendi.

### Proactive Foundation

- `proactive_triggers` tablosu eklendi.
- Follow-up trigger, user mute, daily cap ve quiet-hour policy temeli eklendi.
- Proactive engine flag kapalıyken inert kalır.

### Cost ve Latency Guard

- Kısa sosyal turlar, refinement/self-critique, model çağrı sayısı ve token budget policy ayrıştırıldı.
- AI cost reporting scriptleri ve provider invocation özetleri eklendi.
- Amaç pahalı ikinci pass'leri kalite gerektirmeyen kısa turlardan çıkarmak, kalite isteyen işlerde korumaktır.

### Elyan Model Learning Foundation

- Approved correction dataset export eklendi.
- Training queue preflight ve model artifact promotion policy eklendi.
- Elyan model provider planı Groq yanında shadow/canary/primary aday olarak tasarlandı.
- Canlı routing hâlâ flag ve kalite kapıları arkasındadır.

## Güncel Doğrulama Durumu

Son local gate:

- `npm test`: 855/855 geçti.
- `npx tsc --noEmit`: geçti.
- `npm run evaluate:block-output`: 50/50 geçti.
- `benchmark:security`: 20/20 geçti, secret leak 0%, system prompt leak 0%.
- `benchmark:routing`: 15/15 geçti.
- Full `npm run benchmark`: canlı provider erişimi gerektiren case'de `shared brain inference unavailable` ile kırılabilir; bunu kod regresyonu saymadan provider/env erişimiyle ayrıca doğrula.

## Deploy Disiplini

VPS:

- Host: `root@84.247.172.213`
- Remote repo: `/srv/elyan-backend`
- Public API: `https://api.elyan.dev`
- Standard script: `bash scripts/deploy-v1-release.sh`

Deploy script şunları yapar:

- local `npm ci`, build, test
- remote backup
- repo sync
- remote install, C NLP compile, build, test
- schema bootstrap
- Docker Compose rebuild/restart
- post-deploy probe

İlk 502 restart settle olabilir; probe retry etmeden başarısız sayma.

## Kırmızı Çizgiler

- API/SSE/mobile block contract kırılmaz.
- Provider/system prompt/model adı kullanıcıya sızmaz.
- Secret, private path, raw local file content loglanmaz.
- Client-sent memory/dialogue state authoritative kabul edilmez.
- Başka user'a ait memory/state/context prompt'a girmez.
- Ham dosya/görsel backend'e zorla taşınmaz; mobile local export ve compact context sınırları korunur.
- Desktop gerekmeyen iş desktop'a yönlendirilmez.
- Backend private local computer tools çalıştırmaz.
- Yeni sistemler flag/policy arkasında açılır.

## Öncelikli Sonraki İşler

1. Full benchmark'ı provider bağımlı olmadan deterministic/offline koşabilir hale getir.
2. Turn Envelope yolunu flag arkasında production-shadow modda ölç.
3. Dialogue state merge ve optimistic revision conflict davranışını canlı metriklerle izle.
4. Memory Fabric v2'de tek değerli preference conflict/forget akışını tamamla.
5. Agent loop tool calls için approval policy ve audit event kayıtlarını sıkılaştır.
6. Proactive engine'i önce sadece follow-up kind ile sınırlı canlı shadow modda dene.
7. Compute ayrıştırmada embedding/rerank işini API process dışına taşı.
8. `inference.ts` god-file'ını davranış değiştirmeden küçük modüllere böl.

