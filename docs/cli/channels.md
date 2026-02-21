# elyan channels

Mesajlaşma kanallarını yönetir. Elyan 10 farklı platform destekler.

## Komutlar

### `channels list`

Tüm kanalları listeler.

```bash
elyan channels list
elyan channels list --json
```

Çıktı örneği:
```
ID          TİP        DURUM    AÇIKLAMA
telegram-1  telegram   ✅ aktif  @ElyanBot
discord-1   discord    ✅ aktif  MyServer#general
slack-1     slack      ⚠️ hata   token_expired
```

### `channels status`

Belirli bir kanalın durumunu gösterir.

```bash
elyan channels status telegram-1
```

### `channels add`

Yeni kanal ekler.

```bash
elyan channels add telegram
elyan channels add discord
elyan channels add slack
elyan channels add whatsapp
```

Komut, ilgili kanalın token/webhook yapılandırmasını interaktif olarak sorar.  
`whatsapp` için iki seçenek sunulur:
- QR/Bridge (yerel hesap eşleştirme)
- Cloud API (Meta webhook)

### `channels remove`

Kanal kaldırır.

```bash
elyan channels remove telegram-1
```

### `channels enable` / `disable`

Kanal etkinleştirme/devre dışı bırakma.

```bash
elyan channels enable telegram-1
elyan channels disable slack-1
```

### `channels test`

Kanal bağlantısını test eder.

```bash
elyan channels test telegram-1
```

### `channels login` / `logout`

OAuth/oturum gerektiren kanallar için.

```bash
elyan channels login whatsapp
elyan channels logout whatsapp
```

`whatsapp` login adımı terminalde QR kod gösterir ve bridge token'ını güvenli saklar.

### `channels info`

Kanal detaylarını gösterir.

```bash
elyan channels info telegram-1
```

### `channels sync`

Kanal yapılandırmasını günceller.

```bash
elyan channels sync
```

## Desteklenen Kanallar

| Tip | Dokümantasyon |
|-----|---------------|
| `telegram` | [Telegram →](../channels/telegram.md) |
| `discord` | [Discord →](../channels/discord.md) |
| `slack` | [Slack →](../channels/slack.md) |
| `whatsapp` | [WhatsApp →](../channels/whatsapp.md) |
| `signal` | [Signal →](../channels/signal.md) |
| `matrix` | [Matrix →](../channels/matrix.md) |
| `teams` | [Microsoft Teams →](../channels/teams.md) |
| `google_chat` | [Google Chat →](../channels/google-chat.md) |
| `imessage` | [iMessage →](../channels/imessage.md) |
| `webchat` | [Web Sohbet →](../channels/webchat.md) |

## Kanal Yapılandırması

Kanal ayarları `~/.elyan/elyan.json` dosyasında `channels` dizisi içinde tutulur:

```json5
{
  "channels": [
    {
      "type": "telegram",
      "token": "YOUR_BOT_TOKEN",
      "enabled": true
    }
  ]
}
```
