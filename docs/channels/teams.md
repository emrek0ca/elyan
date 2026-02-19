# Microsoft Teams Entegrasyonu

Elyan, Azure Bot Framework aracılığıyla Microsoft Teams'e bağlanır.

## Gereksinimler

- Microsoft Azure hesabı
- Azure Bot Services

## Azure Bot Oluşturma

1. [Azure Portal](https://portal.azure.com) → **Azure Bot** kaynağı oluşturun
2. Tip: **Multi Tenant**
3. Bot handle (benzersiz ID) girin
4. **App ID** ve **App Secret** oluşturun

### Messaging Endpoint

Azure Bot → **Settings**:

```
Messaging Endpoint: https://yourdomain.com/teams/webhook
```

### Teams Kanalını Etkinleştir

Azure Bot → **Channels** → **Microsoft Teams** → **Save**

## Kurulum

```bash
elyan channels add teams
```

veya `~/.elyan/config.json5`:

```json5
{
  "channels": [
    {
      "type": "teams",
      "app_id": "xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx",
      "app_secret": "xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx",
      "webhook_path": "/teams/webhook",
      "enabled": true
    }
  ]
}
```

## Teams Uygulaması Paketi

Teams'e uygulama olarak yükleme için `manifest.json` oluşturun:

```json
{
  "id": "YOUR_APP_GUID",
  "name": {
    "short": "Elyan",
    "full": "Elyan AI Asistan"
  },
  "bots": [
    {
      "botId": "YOUR_APP_ID",
      "scopes": ["personal", "team", "groupchat"]
    }
  ]
}
```

Bu dosyayı `manifest.zip` olarak paketleyin ve Teams Admin Center'dan yükleyin.

## Desteklenen Özellikler

| Özellik | Durum |
|---------|-------|
| Kişisel sohbet (1-1) | ✅ |
| Kanal mesajı | ✅ |
| Grup sohbeti | ✅ |
| @mention | ✅ |
| Adaptive Cards | ✅ |
| Dosya gönderme | ✅ |
| Mesaj güncelleme | ✅ |

## Adaptive Card Desteği

Zengin yanıtlar için Adaptive Card:

```python
card = {
    "type": "AdaptiveCard",
    "body": [
        {"type": "TextBlock", "text": "Görev tamamlandı!", "weight": "bolder"}
    ]
}
```

## Sorun Giderme

**"Unauthorized" (401):**
- App ID ve Secret doğru mu?
- Bearer token süresi dolmuş olabilir (otomatik yenilenir)

**Mesajlar gelmiyor:**
- Messaging Endpoint URL erişilebilir mi?
- Azure Bot → Test in Web Chat ile bağlantıyı test edin

**@mention çalışmıyor:**
- Bot kanal mesajını dinliyor mu? `allowed_channels` boş olmalı
