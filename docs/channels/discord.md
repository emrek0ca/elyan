# Discord Entegrasyonu

Elyan, Discord Bot API üzerinden sunucu ve DM mesajlarını yönetebilir.

## Gereksinimler

- Discord hesabı
- Discord Geliştirici Portalı'nda uygulama/bot

## Bot Oluşturma

1. [Discord Geliştirici Portalı](https://discord.com/developers/applications)'na gidin
2. **New Application** → bot adı girin
3. **Bot** sekmesi → **Add Bot**
4. **Token** → **Reset Token** → kopyalayın
5. **Privileged Gateway Intents** altında etkinleştirin:
   - `SERVER MEMBERS INTENT`
   - `MESSAGE CONTENT INTENT`

## Bot'u Sunucuya Ekle

**OAuth2 → URL Generator** sayfasında:
- Scope: `bot`
- Permissions: `Send Messages`, `Read Message History`, `Add Reactions`

Oluşturulan URL ile botu sunucuya davet edin.

## Kurulum

```bash
elyan channels add discord
# Token sorar
```

veya `~/.elyan/config.json5`:

```json5
{
  "channels": [
    {
      "type": "discord",
      "token": "MTIzNDU2Nzg5MDEyMzQ1Njc4.XXXXXX.xxxxxxxxxxxxxxxxxxxxxxxxxxx",
      "allowed_guilds": [],      // Boş = tüm sunucular
      "allowed_channels": [],    // Boş = tüm kanallar
      "enabled": true
    }
  ]
}
```

## Filtreler

```json5
{
  "type": "discord",
  "token": "...",
  "allowed_guilds": ["123456789012345678"],     // Sunucu ID
  "allowed_channels": ["987654321098765432"],   // Kanal ID
  "respond_to_mentions_only": false
}
```

ID'yi kopyalamak için Discord'da **Geliştirici Modu**nu açın:
*Ayarlar → Gelişmiş → Geliştirici Modu*

## Desteklenen Özellikler

| Özellik | Durum |
|---------|-------|
| DM mesajı | ✅ |
| Sunucu kanalı | ✅ |
| Embed mesaj | ✅ |
| Dosya gönderme | ✅ |
| Slash komutları | ✅ |
| Thread desteği | ✅ |
| Ses kanalı | ❌ |

## Sorun Giderme

**"Improper token" hatası:**
- Token'da boşluk var mı kontrol edin
- Token yenilenmesi gerekiyor olabilir: Geliştirici Portalı → Bot → Reset Token

**Message Content görmüyor:**
- Geliştirici Portalı → Bot → **Message Content Intent** etkinleştirin

**"Missing Access" hatası:**
- Bot'un sunucuda doğru izinleri var mı?
