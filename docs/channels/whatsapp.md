# WhatsApp Entegrasyonu

Elyan, WhatsApp için iki mod destekler:

- `bridge` (yerel QR eşleştirme, hızlı başlangıç)
- `cloud` (Meta WhatsApp Cloud API + webhook, bot-benzeri üretim modu)

## Hızlı Kurulum (Bridge / QR)

```bash
elyan channels login whatsapp
```

Komut:
- Yerel WhatsApp bridge runtime'ını hazırlar
- Terminalde QR kod üretir
- Telefon ile eşleşmeyi tamamlar
- Kanalı `~/.elyan/elyan.json` içine otomatik kaydeder

## Cloud API Kurulumu (Bot Benzeri)

```bash
elyan channels add whatsapp
```

Kanal ekleme adımında `2=Cloud API` seçin ve şunları girin:
- `phone_number_id`
- `access_token`
- `verify_token` (boş bırakılırsa otomatik üretilir)

Webhook endpoint:

```text
/whatsapp/webhook
```

Meta dashboard tarafında:
- Verify URL: `https://<public-domain>/whatsapp/webhook`
- Verify Token: CLI'da verdiğiniz `verify_token`

## Onboarding İçinden Kurulum

```bash
elyan onboard
```

Kanal adımında **WhatsApp (QR ile bağlan)** seçeneğini seçin.

## Güvenlik

- Bridge sadece `127.0.0.1` üzerinde dinler (dış ağa açık değildir)
- Bridge API erişimi için bearer benzeri bir local token kullanılır
- Token mümkünse macOS Keychain'de saklanır (`WHATSAPP_BRIDGE_TOKEN`)
- Cloud mode tokenları mümkünse Keychain'de saklanır (`WHATSAPP_ACCESS_TOKEN`, `WHATSAPP_VERIFY_TOKEN`)
- WhatsApp mesaj şifrelemesi WhatsApp tarafında uçtan uca korunur

## Yapılandırma Örneği

```json5
{
  "channels": [
    {
      "type": "whatsapp",
      "id": "whatsapp",
      "mode": "bridge",
      "enabled": true,
      "bridge_url": "http://127.0.0.1:18792",
      "bridge_token": "$WHATSAPP_BRIDGE_TOKEN",
      "session_dir": "~/.elyan/channels/whatsapp/whatsapp",
      "auto_start_bridge": true
    }
  ]
}
```

Cloud mode örneği:

```json5
{
  "channels": [
    {
      "type": "whatsapp",
      "id": "whatsapp",
      "mode": "cloud",
      "enabled": true,
      "phone_number_id": "123456789012345",
      "access_token": "$WHATSAPP_ACCESS_TOKEN",
      "verify_token": "$WHATSAPP_VERIFY_TOKEN",
      "webhook_path": "/whatsapp/webhook"
    }
  ]
}
```

## Sık Komutlar

```bash
elyan channels login whatsapp
elyan channels info whatsapp
elyan channels status
elyan channels logout whatsapp
```

## Sorun Giderme

**Node.js bulunamadı**
- Node.js 18+ kurun ve tekrar deneyin.

**QR çıkıyor ama eşleşme olmuyor**
- Telefonda `WhatsApp > Bağlı Cihazlar > Cihaz Bağla` akışını kullanın.
- VPN/proxy varsa kapatıp tekrar deneyin.

**Gateway başlatıldığında WhatsApp bağlanmıyor**
- `elyan channels login whatsapp` ile tekrar eşleştirin.
- `elyan gateway logs --filter whatsapp` ile bridge/adapter loglarını kontrol edin.
