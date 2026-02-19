# elyan gateway

Gateway, gelen mesajları tüm kanallardan alır, Elyan agent'a yönlendirir ve yanıtları geri gönderir.

## Komutlar

### `gateway start`

Gateway'i başlatır.

```bash
elyan gateway start                   # Ön planda
elyan gateway start --daemon          # Arka planda (daemon)
elyan gateway start --port 8765       # Özel port
```

| Seçenek | Varsayılan | Açıklama |
|---------|-----------|----------|
| `--daemon` | `false` | Arka planda çalıştır |
| `--port` | `8765` | Dinleme portu |

### `gateway stop`

Çalışan gateway'i durdurur.

```bash
elyan gateway stop
```

### `gateway restart`

Gateway'i yeniden başlatır.

```bash
elyan gateway restart
elyan gateway restart --daemon
```

### `gateway status`

Mevcut durumu gösterir.

```bash
elyan gateway status
```

Çıktı örneği:
```
Gateway:  çalışıyor  (PID 12345)
Port:     8765
Uptime:   2s 14d 6h 32m
Channels: telegram(✅), discord(✅), slack(⚠️)
```

### `gateway health`

Sağlık kontrolü yapar.

```bash
elyan gateway health
```

### `gateway logs`

Gateway günlüklerini gösterir.

```bash
elyan gateway logs                    # Son 50 satır
elyan gateway logs --tail 200         # Son 200 satır
elyan gateway logs --level debug      # Debug seviyesi
elyan gateway logs --filter "ERROR"   # Filtrele
```

| Seçenek | Varsayılan | Açıklama |
|---------|-----------|----------|
| `--tail` | `50` | Gösterilecek satır sayısı |
| `--level` | `info` | Log seviyesi filtresi |
| `--filter` | — | Arama terimi |

### `gateway reload`

Yapılandırmayı yeniden yükler (sıfırlamadan).

```bash
elyan gateway reload
```

## Daemon Modu

Daemon modunda gateway arka planda çalışır. PID dosyası `~/.elyan/gateway.pid` konumuna kaydedilir.

```bash
# Başlat
elyan gateway start --daemon

# Dur
elyan gateway stop

# Otomatik başlatma için sistem servisi kur
elyan service install
```

## Port Yapılandırması

```bash
# CLI ile
elyan gateway start --port 9000

# Kalıcı ayar
elyan config set gateway.port 9000
```

## Sorun Giderme

```bash
# Hangi süreç portu kullanıyor?
lsof -i :8765

# Gateway günlükleri
elyan gateway logs --level debug

# Tam sistem tanılaması
elyan doctor --check gateway
```
