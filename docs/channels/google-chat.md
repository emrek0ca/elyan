# Google Chat Entegrasyonu

Elyan, Google Chat'e iki farklı modda bağlanabilir: **Webhook** (giden mesaj) ve **Bot** (çift yönlü).

## Mod Seçimi

| Mod | Kullanım |
|-----|----------|
| `webhook` | Yalnızca Google Chat'e mesaj göndermek |
| `bot` | Mesaj almak ve göndermek |

## Webhook Modu (Basit)

### Gelen Webhook URL'si

Google Chat → Boşluk → **Yönet → Apps → Webhooks → Ekle**

```json5
{
  "channels": [
    {
      "type": "google_chat",
      "mode": "webhook",
      "webhook_url": "https://chat.googleapis.com/v1/spaces/SPACE/messages?key=KEY&token=TOKEN",
      "enabled": true
    }
  ]
}
```

Bu modda Elyan yalnızca mesaj **gönderebilir**, alamaz.

## Bot Modu (Tam Entegrasyon)

### Google Cloud Kurulumu

1. **Google Cloud Console** → API'leri Etkinleştir → **Google Chat API**
2. **Kimlik Bilgileri** → Hizmet Hesabı oluşturun
3. Hizmet hesabına JSON anahtar dosyası indirin
4. **Pub/Sub API**'ı etkinleştirin

### Chat API Yapılandırması

Google Cloud → **Google Chat API → Yapılandırma**:

- **Bağlantı Ayarları**: Cloud Pub/Sub
- **Pub/Sub konu**: `projects/YOUR_PROJECT/topics/elyan-chat`

### Kurulum

```bash
elyan channels add google_chat
```

veya `~/.elyan/config.json5`:

```json5
{
  "channels": [
    {
      "type": "google_chat",
      "mode": "bot",
      "service_account_file": "/path/to/service-account.json",
      "project_id": "your-gcp-project",
      "subscription_id": "elyan-chat-sub",
      "enabled": true
    }
  ]
}
```

## Desteklenen Özellikler

| Özellik | Webhook | Bot |
|---------|---------|-----|
| Metin gönderme | ✅ | ✅ |
| Kart (Card) mesajı | ✅ | ✅ |
| Mesaj alma | ❌ | ✅ |
| Thread reply | ❌ | ✅ |
| @mention | ❌ | ✅ |
| Slash komutları | ❌ | ✅ |
| Dosya gönderme | ❌ | ✅ |

## Card Mesajı

Google Chat zengin kart formatı:

```python
card = {
    "cardsV2": [{
        "card": {
            "header": {"title": "Görev Tamamlandı"},
            "sections": [{
                "widgets": [{
                    "textParagraph": {"text": "Analiz raporu hazırlandı."}
                }]
            }]
        }
    }]
}
```

## Sorun Giderme

**Pub/Sub mesajlar gelmiyor:**
- Hizmet hesabı `roles/pubsub.subscriber` rolüne sahip mi?
- Subscription doğru Chat konusuna abone mi?

**"Invalid webhook URL":**
- URL'nin sona erme tarihi var mı? Google Chat webhook URL'leri sona erebilir
