# WhatsApp Entegrasyonu

Elyan, WhatsApp Business API (Meta Cloud API) üzerinden mesajlaşır.

!!! info "Business API Gereksinimi"
    WhatsApp entegrasyonu, kişisel WhatsApp hesapları için **çalışmaz**. WhatsApp Business API erişimi gerektirir.

## Gereksinimler

- Meta Business hesabı
- WhatsApp Business API erişimi
- Onaylı telefon numarası

## Meta Developer Kurulumu

1. [developers.facebook.com](https://developers.facebook.com) → Uygulama oluşturun
2. **WhatsApp** ürününü ekleyin
3. **Test telefon numarası** alın
4. **Webhooks** yapılandırın

### Webhook Yapılandırması

Meta Dashboard → **WhatsApp → Configuration → Webhooks**:
- Callback URL: `https://yourdomain.com/whatsapp/webhook`
- Verify Token: herhangi bir gizli dize
- Subscribe: `messages`

## Kurulum

```bash
elyan channels add whatsapp
```

veya `~/.elyan/config.json5`:

```json5
{
  "channels": [
    {
      "type": "whatsapp",
      "phone_number_id": "123456789012345",
      "access_token": "EAAxxxxxxxxxxxxxxxxxxxxxx",
      "verify_token": "my_verify_token_here",
      "webhook_path": "/whatsapp/webhook",
      "enabled": true
    }
  ]
}
```

## Mesaj Şablonları

İlk mesaj her zaman onaylı bir şablonla başlamalıdır (Meta politikası):

```json5
{
  "type": "whatsapp",
  "access_token": "...",
  "welcome_template": "elyan_welcome",
  "template_language": "tr"
}
```

## Desteklenen Özellikler

| Özellik | Durum |
|---------|-------|
| Metin mesajı | ✅ |
| Görsel/video | ✅ |
| Belge | ✅ |
| Konum | ✅ |
| Sesli mesaj | ✅ |
| Etkileşimli butonlar | ✅ |
| Liste menüsü | ✅ |
| Grup mesajı | ❌ |

## Üretim Onayı

Test ortamında yalnızca beyaz listedeki numaralara mesaj gönderilebilir. Üretim için:

1. Meta Business hesabı doğrulaması
2. WhatsApp Business hesabı onayı
3. Telefon numarası geçiş (test → üretim)

## Sorun Giderme

**"Invalid access token":**
- Token süresi dolmuş olabilir. Kalıcı token için sistem kullanıcısı oluşturun

**Webhook doğrulanamıyor:**
- `verify_token` Meta Dashboard ile eşleşiyor mu?
- URL genel erişime açık mı?

**Mesaj gönderilemiyor:**
- Alıcı son 24 saat içinde mesaj gönderdi mi? (24 saat kuralı)
- Şablon kullanmayı deneyin
