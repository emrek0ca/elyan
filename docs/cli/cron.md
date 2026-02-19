# elyan cron

Zamanlanmış görev yönetimi. Cron ifadeleriyle Elyan görevlerini otomatik olarak çalıştırın.

## Komutlar

### `cron list`

Tüm cron işlerini listeler.

```bash
elyan cron list
```

Çıktı:
```
ID          İFADE           DURUM    SON ÇALIŞMA      SONRAKI
news-daily  0 8 * * *       ✅ aktif  14 Aug 08:00     15 Aug 08:00
cleanup     0 0 * * 0       ✅ aktif  11 Aug 00:00     18 Aug 00:00
report      30 17 * * 1-5   ⚪ pasif  —                —
```

### `cron add`

Yeni cron işi ekler.

```bash
elyan cron add \
  --expression "0 8 * * *" \
  --prompt "Günün haberlerini özetle ve Telegram'a gönder" \
  --channel telegram-1
```

| Seçenek | Açıklama |
|---------|----------|
| `--expression` | Cron ifadesi (5 alan) |
| `--prompt` | Çalıştırılacak görev açıklaması |
| `--channel` | Yanıtın gönderileceği kanal ID |
| `--user-id` | Mesajın sahibi kullanıcı |

### `cron rm` / `remove`

Cron işi kaldırır.

```bash
elyan cron rm news-daily
elyan cron remove news-daily
```

### `cron enable` / `disable`

Cron işini etkinleştirir/devre dışı bırakır.

```bash
elyan cron enable report
elyan cron disable cleanup
```

### `cron run`

Cron işini hemen (zamanından bağımsız) çalıştırır.

```bash
elyan cron run news-daily
```

### `cron history`

Belirli bir işin geçmiş çalışmalarını gösterir.

```bash
elyan cron history news-daily
```

### `cron next`

Bir sonraki çalışma zamanını gösterir.

```bash
elyan cron next news-daily
```

### `cron status`

Cron motorunun genel durumunu gösterir.

```bash
elyan cron status
```

## Cron İfadeleri

```
┌───────────── dakika (0-59)
│ ┌───────────── saat (0-23)
│ │ ┌───────────── ay günü (1-31)
│ │ │ ┌───────────── ay (1-12)
│ │ │ │ ┌───────────── hafta günü (0-6, 0=Pazar)
│ │ │ │ │
* * * * *
```

| İfade | Açıklama |
|-------|----------|
| `0 8 * * *` | Her gün saat 08:00 |
| `*/30 * * * *` | Her 30 dakikada bir |
| `0 9 * * 1` | Her Pazartesi 09:00 |
| `0 0 1 * *` | Her ayın 1'i gece yarısı |
| `30 17 * * 1-5` | Hafta içi 17:30 |

## Kalıcı Depolama

Cron işleri `~/.elyan/cron_jobs.json` dosyasına kaydedilir ve sistem yeniden başlatılsa bile korunur.

## Kullanım Örnekleri

```bash
# Sabah haber özeti
elyan cron add \
  --expression "0 7 * * 1-5" \
  --prompt "Teknoloji haberlerini özetle, 5 madde halinde gönder" \
  --channel telegram-1

# Haftalık rapor
elyan cron add \
  --expression "0 18 * * 5" \
  --prompt "Bu haftanın yapılan görevlerini özetle ve istatistikleri raporla" \
  --channel slack-1

# Disk temizliği hatırlatıcı
elyan cron add \
  --expression "0 10 1 * *" \
  --prompt "İndirmeler klasörünü kontrol et, 30 günden eski dosyaları listele" \
  --channel telegram-1
```
