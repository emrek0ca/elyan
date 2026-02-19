# Slack Entegrasyonu

Elyan, Slack Bolt SDK aracılığıyla Slack çalışma alanlarına bağlanır.

## Gereksinimler

- Slack çalışma alanı
- Slack uygulaması (App)

## Slack Uygulaması Oluşturma

1. [api.slack.com/apps](https://api.slack.com/apps) → **Create New App** → **From scratch**
2. App adı ve çalışma alanını seçin

### İzinler

**OAuth & Permissions → Scopes → Bot Token Scopes:**

```
app_mentions:read
channels:history
channels:read
chat:write
groups:history
im:history
im:read
im:write
mpim:history
users:read
```

### Event Subscriptions

1. **Event Subscriptions** → Enable Events
2. **Request URL**: `https://yourdomain.com/slack/events`
3. **Subscribe to bot events**: `app_mention`, `message.im`, `message.channels`

### Yükleme

**Install to Workspace** → **Bot User OAuth Token** kopyalayın.

## Kurulum

```bash
elyan channels add slack
```

veya `~/.elyan/config.json5`:

```json5
{
  "channels": [
    {
      "type": "slack",
      "bot_token": "xoxb-xxxxxxxxxxxx-xxxxxxxxxxxx-xxxxxxxxxxxxxxxxxxxxxxxx",
      "app_token": "xapp-1-xxxxxxxxxxxx-xxxxxxxxxxxxx-xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx",
      "signing_secret": "xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx",
      "socket_mode": true,
      "enabled": true
    }
  ]
}
```

## Socket Mode (Önerilen)

Socket Mode ile dış URL gerekmez. Yerel geliştirme için idealdir.

1. **App-Level Tokens** → Generate → Scope: `connections:write`
2. **Socket Mode** → Enable
3. `app_token` değerini yapılandırmaya ekleyin

## Webhook Mode

Dış sunucu gerektirir ancak daha az kaynak kullanır:

```json5
{
  "type": "slack",
  "bot_token": "xoxb-...",
  "signing_secret": "...",
  "socket_mode": false,
  "webhook_path": "/slack/events"
}
```

## Desteklenen Özellikler

| Özellik | Durum |
|---------|-------|
| DM mesajı | ✅ |
| Kanal mesajı | ✅ |
| @mention | ✅ |
| Block Kit (butonlar) | ✅ |
| Dosya yükleme | ✅ |
| Thread reply | ✅ |
| Modal | ✅ |

## Sorun Giderme

**"invalid_auth" hatası:**
- `bot_token` ile `xoxb-` ile başlıyor mu?
- Uygulama çalışma alanına yüklendi mi?

**Events gelmiyor (Webhook mode):**
- URL doğrulanabiliyor mu? Slack → Event Subscriptions → URL'yi test edin

**Socket Mode bağlanamıyor:**
- `app_token` ile `xapp-` ile başlıyor mu?
