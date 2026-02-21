# Gateway REST API

Elyan Gateway, `http://localhost:8765` adresinde bir HTTP API sunar.

## Kimlik Doğrulama

API key yapılandırıldıysa tüm isteklerde header gönderin:

```
Authorization: Bearer YOUR_AUTH_TOKEN
```

Yapılandırma:

```bash
elyan config set gateway.auth_token your_secret_token
```

## Uç Noktalar

### `GET /api/health`

Sistem sağlık durumu.

```bash
curl http://localhost:8765/api/health
```

```json
{
  "status": "ok",
  "version": "18.0.0",
  "uptime_seconds": 3672,
  "gateway_pid": 12345
}
```

### `GET /api/analytics`

Kullanım istatistikleri.

```bash
curl http://localhost:8765/api/analytics
```

```json
{
  "total_requests": 1247,
  "success_rate": 0.97,
  "avg_response_time_ms": 843,
  "model": "groq/llama-3.3-70b-versatile",
  "total_cost_usd": 0.00,
  "requests_last_24h": 234,
  "top_tools": [
    {"name": "web_search", "count": 312}
  ],
  "channels": {
    "telegram": 789,
    "discord": 312
  }
}
```

### `GET /api/tasks`

Aktif ve son tamamlanan görevler.

```bash
curl http://localhost:8765/api/tasks
```

```json
{
  "active": [
    {
      "id": "task_abc123",
      "user_id": "user123",
      "description": "Web araştırması: yapay zeka trendleri",
      "started_at": "2025-08-14T15:30:00Z",
      "status": "running"
    }
  ],
  "recent": [
    {
      "id": "task_xyz789",
      "description": "Excel raporu oluştur",
      "completed_at": "2025-08-14T15:28:00Z",
      "duration_ms": 4200,
      "success": true
    }
  ]
}
```

### `POST /api/tasks`

Yeni görev oluştur.

```bash
curl -X POST http://localhost:8765/api/tasks \
  -H "Content-Type: application/json" \
  -d '{"text": "Bugünün hava durumunu özetle", "channel": "webchat", "user_id": "web_user"}'
```

**İstek gövdesi:**

```json
{
  "text": "Görev açıklaması",
  "channel": "webchat",
  "user_id": "web_user_1"
}
```

**Yanıt:**

```json
{
  "task_id": "task_abc123",
  "status": "queued"
}
```

### `GET /api/memory/stats`

Bellek sistemi istatistikleri.

```bash
curl http://localhost:8765/api/memory/stats
```

```json
{
  "total_entries": 1247,
  "index_size_mb": 24.3,
  "last_indexed": "2025-08-14T15:32:00Z",
  "users": 3
}
```

### `GET /api/activity`

Son aktivite günlüğü.

```bash
curl http://localhost:8765/api/activity
curl "http://localhost:8765/api/activity?limit=50"
```

```json
{
  "events": [
    {
      "ts": "2025-08-14T15:32:41Z",
      "type": "message",
      "user": "user123",
      "channel": "telegram",
      "tool": "web_search",
      "duration_ms": 843
    }
  ]
}
```

## Webhook Uç Noktaları

Kanal webhook'ları ayrı yollarda bulunur:

| Kanal | Yol |
|-------|-----|
| Telegram | `/telegram/webhook` |
| Slack | `/slack/events` |
| WhatsApp | `/whatsapp/webhook` |
| Teams | `/teams/webhook` |
| Google Chat | `/gchat/webhook` |
| Web Chat | `/ws/chat` (WebSocket) |

## Hata Yanıtları

```json
{
  "error": "unauthorized",
  "message": "Geçerli bir auth token gereklidir",
  "code": 401
}
```

| Kod | Açıklama |
|-----|----------|
| `400` | Geçersiz istek gövdesi |
| `401` | Kimlik doğrulama hatası |
| `404` | Uç nokta bulunamadı |
| `429` | Rate limit aşıldı |
| `500` | Sunucu hatası |
