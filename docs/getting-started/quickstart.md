# Hızlı Başlangıç

## 5 Dakikada Elyan

### 1. Kurulum

```bash
git clone https://github.com/your-org/elyan.git && cd elyan
bash install.sh
source .venv/bin/activate
```

### 2. API Anahtarı

En az bir LLM sağlayıcısı gereklidir. Ücretsiz seçenekler:

- **Groq** (önerilen): [console.groq.com](https://console.groq.com) → Free tier
- **Google Gemini**: [aistudio.google.com](https://aistudio.google.com)

```bash
elyan config set models.default.provider groq
elyan config set models.default.api_key "YOUR_GROQ_API_KEY"
```

### 3. Telegram Botu (isteğe bağlı)

1. [@BotFather](https://t.me/BotFather) ile yeni bot oluşturun
2. Token'ı kaydedin:

```bash
elyan config set channels.telegram.token "YOUR_TELEGRAM_BOT_TOKEN"
```

### 4. Gateway Başlatma

```bash
elyan gateway start
# veya arka planda:
elyan gateway start --daemon
```

### 5. Test

```bash
elyan health
# Telegram'dan bot'a "merhaba" yazın
```

## Temel Komutlar

```bash
elyan gateway status    # Çalışıyor mu?
elyan doctor            # Sorun var mı?
elyan channels list     # Bağlı kanallar
elyan models list       # Kullanılabilir modeller
elyan dashboard         # Web arayüzünü aç
```

## İlk Görev

Telegram'dan (veya Dashboard'dan) deneyin:

```
Merhaba! Bugün hava durumu nedir?
```

```
Ekran görüntüsü al
```

```
Masaüstündeki dosyaları listele
```
