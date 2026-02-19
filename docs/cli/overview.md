# CLI Genel Bakış

Elyan, `elyan` komut satırı arayüzü (CLI) ile tam olarak yönetilebilir.

## Kurulum

```bash
pip install -e .          # Geliştirme ortamı
# veya
pip install elyan-cli     # PyPI (yakında)
```

## Temel Kullanım

```
elyan <komut> [alt-komut] [seçenekler]
```

## Komut Listesi

| Komut | Açıklama |
|-------|----------|
| `gateway` | Gateway başlat/durdur/yönet |
| `channels` | Mesajlaşma kanallarını yönet |
| `models` | AI model yapılandırması |
| `skills` | Beceri eklentilerini yönet |
| `memory` | Bellek ve vektör indeks yönetimi |
| `cron` | Zamanlanmış görevler |
| `security` | Güvenlik denetimi ve ayarları |
| `doctor` | Sistem tanılaması ve düzeltme |
| `config` | Yapılandırma dosyası yönetimi |
| `agents` | Çoklu-agent yönetimi |
| `browser` | Tarayıcı otomasyonu |
| `voice` | Ses tanıma ve sentezi |
| `webhooks` | Webhook yönetimi |
| `message` | Mesaj gönder/al |
| `dashboard` | Web arayüzünü aç |
| `onboard` | İlk kurulum sihirbazı |
| `service` | Sistem servisi kur/kaldır |
| `doctor` | Tanılama |
| `health` | Hızlı sağlık özeti |
| `status` | Genel durum |
| `version` | Sürüm bilgisi |
| `completion` | Shell otomatik tamamlama |

## Hızlı Başlangıç

```bash
# 1. Kurulum sihirbazını çalıştır
elyan onboard

# 2. Gateway'i başlat
elyan gateway start

# 3. Durumu kontrol et
elyan status

# 4. Telegram kanalını ekle
elyan channels add telegram

# 5. Sistem tanılaması
elyan doctor
```

## Global Seçenekler

```
--help      Bu yardım mesajını göster
--version   Sürüm bilgisi
```

## Shell Otomatik Tamamlama

=== "zsh"
    ```bash
    elyan completion install --shell zsh
    source ~/.zshrc
    ```

=== "bash"
    ```bash
    elyan completion install --shell bash
    source ~/.bashrc
    ```

=== "fish"
    ```bash
    elyan completion install --shell fish
    ```

## Yapılandırma Dosyası

Varsayılan yapılandırma: `~/.elyan/config.json5`

```bash
elyan config show          # Tüm ayarları görüntüle
elyan config get model     # Tek değer oku
elyan config set model groq # Değer ata
```

## Günlükler

```bash
elyan gateway logs              # Son 50 satır
elyan gateway logs --tail 100   # Son 100 satır
elyan gateway logs --filter ERROR
```
