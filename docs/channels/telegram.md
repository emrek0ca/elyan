# Telegram Entegrasyonu

Elyan, Telegram Bot API üzerinden mesaj alıp gönderebilir.

## Gereksinimler

- Telegram hesabı
- Bot token (`@BotFather` üzerinden alınır)

## Bot Oluşturma

1. Telegram'da `@BotFather` ile sohbet başlatın
2. `/newbot` komutunu gönderin
3. Bot adı ve kullanıcı adı belirleyin
4. Token'ı kopyalayın: `YOUR_TELEGRAM_BOT_TOKEN`

## Kurulum

```bash
elyan channels add telegram
# Token sorar, yapıştırın
```

Veya `~/.elyan/config.json5` dosyasına manuel ekleyin:

```json5
{
  "channels": [
    {
      "type": "telegram",
      "token": "YOUR_TELEGRAM_BOT_TOKEN",
      "allowed_users": [],    // Boş = herkese açık
      "enabled": true
    }
  ]
}
```

## Erişim Kontrolü

Yalnızca belirli kullanıcılara izin vermek için `allowed_users` listesini kullanın:

```json5
{
  "type": "telegram",
  "token": "...",
  "allowed_users": [123456789, 987654321]
}
```

Kullanıcı ID'sini öğrenmek: `@userinfobot`'a `/start` gönderin.

## Grup Sohbeti

Bot gruba eklendiğinde:

```json5
{
  "type": "telegram",
  "token": "...",
  "allowed_chats": [-100123456789],   // Grup chat_id (negatif)
  "respond_to_mentions_only": true     // Yalnızca @mention
}
```

## Desteklenen Özellikler

| Özellik | Durum |
|---------|-------|
| 1-1 mesaj | ✅ |
| Grup mesajı | ✅ |
| Komutlar (`/start`, `/help`) | ✅ |
| Markdown (HTML) | ✅ |
| Fotoğraf/dosya gönderme | ✅ |
| Inline butonlar | ✅ |
| Ses mesajı | ✅ |
| Konum | ✅ |

## Komutlar

Bot üzerinde tanımlı slash komutları:

| Komut | Açıklama |
|-------|----------|
| `/start` | Hoş geldiniz mesajı |
| `/help` | Yardım |
| `/status` | Sistem durumu |
| `/reset` | Konuşmayı sıfırla |
| `/screenshot` | Ekran görüntüsü |

## Sorun Giderme

**"Unauthorized" hatası:**
- Token doğru mu? `@BotFather` → `/mybots` → token'ı kopyalayın

**Mesajlar gelmiyor:**
- `elyan channels test telegram-1`
- Bot `getWebhookInfo` durumunu kontrol edin

**Polling vs Webhook:**
- Varsayılan: long polling (her ortamda çalışır)
- Webhook için: `elyan config set telegram.webhook_url https://yourdomain.com/webhook`
