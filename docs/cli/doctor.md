# elyan doctor

Sistem tanılaması, sorun tespiti ve otomatik düzeltme.

## Komutlar

### `doctor` (varsayılan)

Kapsamlı sistem tanılaması çalıştırır.

```bash
elyan doctor
```

Çıktı örneği:
```
🔍 Elyan Sistem Tanılaması
──────────────────────────────────────────
[✅] Python 3.12.3
[✅] Bağımlılıklar yüklü (47/47)
[✅] Yapılandırma dosyası geçerli
[✅] Groq API erişimi
[⚠️] Gemini API — anahtar bulunamadı
[✅] Gateway portu (8765) kullanılabilir
[✅] Bellek sistemi normal
[✅] Güvenlik modülü aktif
──────────────────────────────────────────
Sonuç: 7 kontrol geçti, 1 uyarı
```

### `doctor --fix`

Tespit edilen sorunları otomatik olarak düzeltir.

```bash
elyan doctor --fix
```

Otomatik düzeltilebilir sorunlar:
- Eksik Python bağımlılıklarını yükle
- Yapılandırma dosyasını varsayılana sıfırla
- Log dizinini oluştur
- `.env` dosyasındaki API anahtarlarını keychain'e taşı

### `doctor --deep`

Derin tanılama — daha fazla kontrol yapar.

```bash
elyan doctor --deep
```

Ek kontroller:
- Model API gecikme ölçümü
- Bellek indeks bütünlüğü
- Kanal bağlantı testi
- Disk alanı ve RAM kontrolü

### `doctor --report`

Tanılama raporunu dosyaya kaydeder.

```bash
elyan doctor --report
# Çıktı: elyan-doctor-report-20250814.txt
```

### `doctor --check <alan>`

Belirli bir alanı kontrol eder.

```bash
elyan doctor --check gateway
elyan doctor --check security
elyan doctor --check memory
elyan doctor --check models
elyan doctor --check channels
```

## Kontrol Alanları

| Alan | Kontroller |
|------|-----------|
| `python` | Sürüm, bağımlılıklar |
| `config` | Yapılandırma geçerliliği, eksik anahtarlar |
| `gateway` | Port erişilebilirliği, PID dosyası |
| `models` | API anahtarları, bağlantı testi |
| `memory` | Veri tabanı dosyası, indeks bütünlüğü |
| `security` | Rate limiter, audit log, keychain |
| `channels` | Kanal bağlantıları |
| `system` | Disk alanı, RAM, CPU |

## `health` Komutu

Hızlı özet için `health` kullanın:

```bash
elyan health
```

```
Elyan v18.0.0 — ✅ Sağlıklı
Gateway: çalışıyor | Model: groq | Kanallar: 3/3
```

## `status` Komutu

Daha ayrıntılı durum için:

```bash
elyan status
elyan status --deep
elyan status --json
```

## Yaygın Sorunlar

### "Port 8765 kullanımda"

```bash
# Hangi süreç kullanıyor?
lsof -i :8765
# Farklı port kullan
elyan gateway start --port 8766
```

### "API anahtarı bulunamadı"

```bash
elyan models add --provider groq --key YOUR_GROQ_API_KEY
```

### "Bağımlılık eksik"

```bash
elyan doctor --fix
# veya
pip install -r requirements.txt
```

### "Bellek indeks bozuk"

```bash
elyan memory export --file backup.json   # Yedek al
elyan memory clear                        # Temizle
elyan memory import --file backup.json   # Geri yükle
```
