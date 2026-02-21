# Signal Entegrasyonu

Elyan, Signal mesajlaşma uygulamasını **signald** aracı üzerinden destekler.

## Gereksinimler

1. **signald** kurulu ve çalışıyor olmalı ([signald.org](https://signald.org))
2. Bir Signal hesabı (ayrı bir telefon numarası önerilir)

## Kurulum

### 1. signald Kurulumu (Debian/Ubuntu)

```bash
echo 'deb [signed-by=/usr/share/keyrings/signald.gpg] https://updates.signald.org unstable main' \
  | sudo tee /etc/apt/sources.list.d/signald.list
curl -s https://updates.signald.org/apt-signing-key.gpg \
  | sudo gpg --dearmor --output /usr/share/keyrings/signald.gpg
sudo apt update && sudo apt install signald
sudo systemctl start signald
```

### 2. Hesap Kayıt

```bash
# signaldctl ile
signaldctl register +905551234567
signaldctl verify +905551234567 123456  # SMS kodu
```

### 3. elyan.json Yapılandırması

```json5
{
  "channels": [
    {
      "type": "signal",
      "phone_number": "+905551234567",
      "socket_path": "/var/run/signald/signald.sock",
      "enabled": true
    }
  ]
}
```

## HTTP Proxy Modu

[signald-http](https://gitlab.com/signald/signald-http) proxy çalışıyorsa:

```json5
{
  "type": "signal",
  "phone_number": "+905551234567",
  "http_url": "http://localhost:8080",
  "enabled": true
}
```

## Özellikler

| Özellik | Durum |
|---------|-------|
| Metin mesajları | ✅ |
| Resim/dosya gönderme | ✅ |
| Grup mesajları | ✅ |
| Ses mesajları | ✅ |
| Okundu bilgisi | ⚠️ |
| Butonlar/Menü | ❌ |

!!! warning "Güvenlik Notu"
    Signal hesabına ayrı bir telefon numarası kullanın.
    Bot numaranızı başkalarıyla paylaşmayın.
