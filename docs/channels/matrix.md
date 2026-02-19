# Matrix / Element Entegrasyonu

Elyan, Matrix protokolünü **matrix-nio** kütüphanesi üzerinden destekler.

## Gereksinimler

```bash
pip install "matrix-nio[e2e]"   # End-to-end şifreleme
# veya
pip install matrix-nio           # Şifresiz
```

## Bot Hesabı Oluşturma

1. [matrix.org](https://matrix.org/try-matrix/) veya kendi homeserver'ınızda hesap oluşturun
2. Hesapla giriş yapın, access token alın:

```bash
curl -XPOST 'https://matrix.org/_matrix/client/r0/login' \
  -H 'Content-Type: application/json' \
  -d '{"type":"m.login.password","user":"@elyan:matrix.org","password":"<pass>"}'
# Yanıtta: "access_token": "syt_..."
```

## Yapılandırma

```json5
{
  "channels": [
    {
      "type": "matrix",
      "homeserver": "https://matrix.org",
      "user_id": "@elyan:matrix.org",
      "access_token": "syt_...",
      "device_name": "Elyan Bot",
      "allowed_rooms": [],  // Boş = tüm odalar
      "enabled": true
    }
  ]
}
```

## Özellikleri

| Özellik | Durum |
|---------|-------|
| Metin mesajları | ✅ |
| Markdown / HTML | ✅ |
| DM odaları | ✅ |
| Grup odaları | ✅ |
| End-to-end şifreleme | ⚠️ (Ek kurulum) |
| Tepkiler | ✅ |
| Thread'ler | ✅ |
| Butonlar | ❌ |

## Desteklenen Homeserver'lar

- matrix.org (genel)
- element.io
- Synapse (kendi sunucunuz)
- Conduit, Dendrite
