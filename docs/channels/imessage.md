# iMessage / BlueBubbles Entegrasyonu

Elyan, iMessage'a **BlueBubbles Server** üzerinden bağlanır.

!!! warning "macOS Gereksinim"
    iMessage yalnızca macOS'ta çalışır. BlueBubbles Server'ın
    Elyan ile **aynı ağda veya erişilebilir** bir macOS makinede çalışıyor olması gerekir.

## Gereksinimler

1. macOS bilgisayar (BlueBubbles için)
2. [BlueBubbles Server](https://github.com/BlueBubblesApp/bluebubbles-server) kurulu ve çalışıyor
3. REST API + WebSocket modunda açık

## BlueBubbles Server Kurulumu

1. [GitHub Releases](https://github.com/BlueBubblesApp/bluebubbles-server/releases) sayfasından indirin
2. Kurun ve başlatın
3. **Settings → Server Configuration** altında:
   - `Server Port`: `1234` (veya istediğiniz port)
   - `Password`: güçlü bir şifre belirleyin
   - `Private API`: etkinleştirin (tam özellik için)

## Elyan Yapılandırması

```json5
{
  "channels": [
    {
      "type": "imessage",
      "server_url": "http://192.168.1.10:1234",  // BlueBubbles Server IP
      "password": "your_bb_password",
      "allowed_chats": [],   // Boş = tüm sohbetler
      "enabled": true
    }
  ]
}
```

### Belirli Sohbetleri Filtreleme

```json5
{
  "type": "imessage",
  "server_url": "http://192.168.1.10:1234",
  "password": "...",
  "allowed_chats": [
    "iMessage;-;+905551234567",
    "iMessage;+;chat-guid-here"
  ]
}
```

## Desteklenen Özellikler

| Özellik | Durum |
|---------|-------|
| 1-1 sohbet | ✅ |
| Grup sohbeti | ✅ |
| Metin alma/gönderme | ✅ |
| Tepkiler (tapback) | ✅ |
| Okundu bilgisi | ✅ |
| Resim/dosya | ✅ |
| Butonlar/menü | ❌ |
| Markdown | ❌ |

## Sorun Giderme

**Bağlanamıyor:**
- BlueBubbles'ın çalıştığını doğrulayın: `http://server_ip:1234/api/v1/ping`
- Güvenlik duvarı 1234 portuna izin veriyor mu?

**Mesaj gelmiyor:**
- BlueBubbles Private API aktif mi?
- `Full Disk Access` macOS izni verildi mi?
