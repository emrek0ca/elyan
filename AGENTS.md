# Elyan Backend — Agent Reference

> Tek yönlendirme dosyası. Bu belgedeki tüm maddeler tamamlanınca v1 yayına hazırdır.

---

## Proje Özeti

TypeScript/Fastify backend. Drizzle ORM, PostgreSQL, Redis, SSE streaming.

- **Build**: `npm run build` (tsc)
- **Test**: `npm test` (node:test)
- **AI Katmanı**: Groq API (model adı hiçbir yerde kullanıcıya gösterilmez)

---

## Temel Mimari Kurallar

- `brain/inference.ts` → `brain/service.ts` → `tasks/service.ts` zinciri değişmez
- SSE delta'lar öncelikli; REST polling yalnızca fallback
- Ham dosya/görsel sunucuya GİTMEZ — compact block pipeline kullanılır
- Memory job'ları yalnızca TypeScript worker (src/modules/brain/worker.ts) handle eder

---

## V1 Launch Checklist — Son Durum

### Hafta 1 — Mobile Freeze (TAMAMLANDI)
- [x] task_chat_surface.dart 14-field narrow selector
- [x] task_inbox_sheet narrow selector
- [x] task_workspace_shell narrow selector
- [x] _applyOptimisticChatSession sort kaldırıldı

### Hafta 2 — Server Pipeline (TAMAMLANDI)
- [x] vision_reasoning workload (Groq Llama 4 Scout)
- [x] inference.ts multimodal content blocks
- [x] attachment-context.ts visionImages support
- [x] chat/service.ts hasVisionImage routing
- [x] ml-worker/worker.py memory kind filter
- [x] attachment-insights.ts → attachment-context.ts merge

### Hafta 3 — Desktop Routing (TAMAMLANDI)
- [x] routeChatTurn() single public API
- [x] Desktop intent single point
- [x] Free plan + desktop → net kullanıcı mesajı
- [x] Desktop offline → queue + bildirim

### Hafta 4 — Regression (TAMAMLANDI)
- [x] 14 mobile smoke test
- [x] 4 server regression fixture
- [x] AGENTS.md V1 launch checklist

### Kırmızı Çizgiler (asla yapma)
- "Claude"/"Anthropic" adı geçmez
- Ham dosya sunucuya gönderilmez
- Memory/world_signals uydurulmaz
- Desktop gerekmeyen iş desktop'a yönlendirilmez
