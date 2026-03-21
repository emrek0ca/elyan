# elyan models

AI model ve sağlayıcı yönetimi. Elyan Groq, Google Gemini ve Ollama'yı destekler.

## Komutlar

### `models list`

Mevcut model ve sağlayıcıları listeler.

```bash
elyan models list
```

Çıktı örneği:
```
SAĞLAYICI    MODEL                     DURUM    VARSAYILAN
groq         llama-3.3-70b-versatile   ✅ aktif   ⭐
gemini       gemini-2.0-flash          ✅ aktif
ollama       llama3.2:latest           ✅ yerel
```

### `models status`

Model bağlantılarının durumunu gösterir.

```bash
elyan models status
```

### `models test`

Modeli test sorgusuna gönderir.

```bash
elyan models test
elyan models test groq
elyan models test --model llama-3.3-70b-versatile
```

### `models use`

Aktif modeli değiştirir.

```bash
elyan models use groq
elyan models use ollama
```

### `models add`

Yeni sağlayıcı/API anahtarı ekler.

```bash
elyan models add --provider groq --key YOUR_GROQ_API_KEY
elyan models add --provider gemini --key YOUR_GOOGLE_API_KEY
```

API anahtarı güvenli keychain deposuna kaydedilir.

### `models set-default`

Varsayılan modeli atar.

```bash
elyan models set-default groq
elyan models set-default --model gemini-2.0-flash
```

### `models set-fallback`

Yedek modeli atar (birincil hata alırsa).

```bash
elyan models set-fallback ollama
```

### `models cost`

Model kullanım maliyetini rapor eder.

```bash
elyan models cost
elyan models cost --period 7d     # Son 7 gün
elyan models cost --period 30d    # Son 30 gün
```

### `models ollama`

Yerel Ollama yönetimi.

```bash
elyan models ollama list          # Yüklü modeller
elyan models ollama pull llama3.2 # Model indir
elyan models ollama start         # Ollama servisini başlat
elyan models ollama stop          # Ollama servisini durdur
```

## Öncelik Sırası

```
1. Groq    (ücretsiz, en hızlı)  →  llama-3.3-70b-versatile
2. Gemini  (ücretsiz)            →  gemini-2.0-flash
3. Ollama  (yerel)               →  otomatik algıla
```

Bir sağlayıcı hata alırsa bir sonrakine geçilir.

## API Anahtarı Yönetimi

API anahtarları macOS Keychain (veya Linux Secret Service) içinde güvenli olarak saklanır:

```bash
# Ekle
elyan models add --provider groq --key YOUR_GROQ_API_KEY

# Kaldır
elyan config unset groq_api_key
```

Ortam değişkeni alternatifi:

```bash
export GROQ_API_KEY=YOUR_GROQ_API_KEY
export GEMINI_API_KEY=YOUR_GOOGLE_API_KEY
```

## Ollama — Yerel Kurulum

```bash
# Ollama yükle (macOS)
brew install ollama

# Servisi başlat
ollama serve

# Model çek
ollama pull llama3.2

# Elyan'a bağla
elyan models ollama check
```
