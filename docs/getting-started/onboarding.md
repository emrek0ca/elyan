# Onboarding (İlk Kurulum)

`elyan onboard` komutu, Elyan'ı adım adım yapılandıran interaktif bir sihirbaz başlatır.

## Başlatma

```bash
elyan onboard
```

Grafik arayüz olmayan ortamlarda:

```bash
elyan onboard --headless
```

Yalnızca belirli bir kanalı yapılandırmak için:

```bash
elyan onboard --channel telegram
```

## Sihirbaz Adımları

### Adım 1: AI Model Seçimi

```
Hangi AI sağlayıcısını kullanmak istersiniz?

  [1] Groq (ücretsiz, en hızlı) — önerilen
  [2] Google Gemini (ücretsiz)
  [3] Ollama (yerel, internet yok)
  [4] Hepsini yapılandır

Seçiminiz [1]:
```

Groq seçilirse API anahtarı sorulur:

```
Groq API anahtarı (https://console.groq.com'dan ücretsiz alın):
> gsk_xxxxxxxxxxxxx

✅ Groq API bağlantısı test edildi. Yanıt süresi: 342ms
```

### Adım 2: Kanal Seçimi

```
Hangi kanalları eklemek istersiniz? (birden fazla seçilebilir)

  [1] Telegram (en kolay)
  [2] Discord
  [3] Slack
  [4] WhatsApp (QR)
  [5] Web Sohbet (dashboard)
  [6] Diğerleri (Signal, Matrix, Teams, Google Chat, iMessage)
  [7] Şimdi atla

Seçiminiz [1]:
```

### Adım 3: Kanal Yapılandırması

Seçilen kanal(lar) için token/credentials sorulur. Örnek Telegram için:

```
Telegram Bot Token:
(BotFather: /newbot → token kopyalayın)

> 1234567890:AAFxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx

✅ Telegram bağlantısı test edildi. Bot adı: @ElyanBot
```

WhatsApp seçilirse terminalde QR gösterilir:

```text
WhatsApp QR eşleştirme başlatılıyor...
Telefonda WhatsApp > Bağlı Cihazlar > Cihaz Bağla ile QR okutun.
✅ WhatsApp eşleşmesi tamamlandı.
```

### Adım 4: Güvenlik Ayarları

```
Güvenlik modu:

  [1] Balanced (önerilen) — riskli araçlar onay bekler
  [2] Strict — her araç onay bekler
  [3] Permissive — otomatik onay (yalnızca geliştirme için)

Seçiminiz [1]:
```

### Adım 5: Daemon Kurulumu

```
Elyan'ı sistem başlangıcında otomatik başlatmak ister misiniz?

  [E] Evet — sistem servisi kur
  [H] Hayır — manuel başlatacağım

Seçiminiz [E]:
```

`Evet` seçilirse `elyan service install` çalıştırılır.

### Adım 6: Özet ve Doğrulama

```
Kurulum Özeti:
  AI Modeli:  Groq / llama-3.3-70b-versatile
  Kanallar:   Telegram (@ElyanBot)
  Güvenlik:   Balanced
  Daemon:     Aktif

Sistem tanılaması çalıştırılıyor...

  [✅] Python 3.12.3
  [✅] Groq API bağlantısı (342ms)
  [✅] Telegram bağlantısı
  [✅] Gateway portu (8765) kullanılabilir

Elyan hazır! Başlatmak için:

  elyan gateway start

Veya hemen başlatmak için [E] tuşuna basın:
```

## Yapılandırma Dosyası

Onboarding tamamlandıktan sonra `~/.elyan/elyan.json` oluşturulur:

```json5
{
  "version": "18.0",
  "models": {
    "default": "groq",
    "groq_api_key": "gsk_xxx"   // Keychain'de saklanır
  },
  "channels": [
    {
      "type": "telegram",
      "token": "1234...",
      "enabled": true
    }
  ],
  "security": {
    "mode": "balanced"
  },
  "gateway": {
    "port": 8765
  }
}
```

## Yeniden Çalıştırma

Onboarding her zaman yeniden çalıştırılabilir:

```bash
elyan onboard
```

Mevcut yapılandırma üzerine yazar (onay sorulur).

## Headless Mod

CI/CD veya Docker ortamlarında:

```bash
GROQ_API_KEY=gsk_xxx \
TELEGRAM_TOKEN=1234... \
elyan onboard --headless
```

Ortam değişkenlerinden otomatik okur.
